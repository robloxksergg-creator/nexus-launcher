"""In-memory unit tests only. No preflight, CLI, Windows APIs or fixtures."""
import importlib.util
import io
from pathlib import Path
import struct
import unittest
import zipfile

spec = importlib.util.spec_from_file_location('placement_probe_logic', Path(__file__).with_name('probe.py'))
probe = importlib.util.module_from_spec(spec)
spec.loader.exec_module(probe)


class LogicTests(unittest.TestCase):
    def test_native_pending_does_not_consume_stale_success(self):
        result = probe.native_query_result_policy(return_status='STATUS_PENDING',
                     io_status='STATUS_SUCCESS', information=106)
        self.assertEqual(result, {'status': 'INCOMPLETE', 'code': 'COMPLETION_PENDING'})
        self.assertNotIn('span', result)

    def test_native_pending_final_completion_needed(self):
        for io_status in (None, 'STATUS_PENDING'):
            result = probe.native_query_result_policy(return_status='STATUS_PENDING',
                         io_status=io_status, pending_completed=True, information=106)
            self.assertEqual(result['code'], 'FINAL_COMPLETION_UNCONFIRMED')

    def test_native_pending_final_success(self):
        result = probe.native_query_result_policy(return_status='STATUS_PENDING',
                     io_status='STATUS_SUCCESS', pending_completed=True, information=106)
        self.assertEqual(result['span'], (0, 106))

    def test_native_direct_return_not_stale_iosb(self):
        result = probe.native_query_result_policy(return_status='STATUS_ACCESS_DENIED',
                     io_status='STATUS_SUCCESS', information=106)
        self.assertEqual(result['code'], 'NATIVE_QUERY_STATUS')
        result = probe.native_query_result_policy(return_status='STATUS_SUCCESS',
                     io_status='STATUS_PENDING', information=106)
        self.assertEqual(result['disposition'], 'STRUCTURAL_VALIDATION_REQUIRED')

    def test_native_exact_eof_status(self):
        result = probe.native_query_result_policy(return_status='STATUS_NO_MORE_FILES', information=0)
        self.assertEqual(result['disposition'], 'END_NO_RECORDS')
        result = probe.native_query_result_policy(return_status='STATUS_SUCCESS', information=0)
        self.assertEqual(result['code'], 'EMPTY_SUCCESS_NOT_END')

    def test_native_truncation_and_cancel_never_parse(self):
        for status in ('STATUS_BUFFER_OVERFLOW', 'STATUS_BUFFER_TOO_SMALL',
                       'STATUS_INFO_LENGTH_MISMATCH', 'STATUS_CANCELLED'):
            result = probe.native_query_result_policy(return_status=status, information=106)
            self.assertEqual(result['status'], 'INCOMPLETE')
            self.assertNotIn('span', result)

    def test_native_unsupported_blocked_unknown_refused(self):
        for status in ('STATUS_NOT_SUPPORTED', 'STATUS_NOT_IMPLEMENTED', 'STATUS_INVALID_INFO_CLASS'):
            self.assertEqual(probe.native_query_result_policy(return_status=status)['status'], 'BLOCKED')
        self.assertEqual(probe.native_query_result_policy(return_status='STATUS_OTHER')['status'], 'REFUSED')

    def test_native_numeric_status_not_treated_as_symbol(self):
        result = probe.native_query_result_policy(return_status=0, information=106)
        self.assertEqual(result['code'], 'NATIVE_STATUS_ARGUMENTS')

    def test_page_win32_capacity_is_not_length(self):
        for information in (None, 0, 106, probe.MAX_DIR_BUFFER):
            result = probe.page_length_policy(api='win32', completion='success',
                         capacity=probe.MAX_DIR_BUFFER, information=information)
            self.assertEqual(result, {'status': 'BLOCKED', 'code': 'WIN32_NO_DOCUMENTED_BYTE_COUNT'})
            self.assertNotIn('span', result)

    def test_page_native_count_validation(self):
        for information in (None, -1, True, 65537):
            result = probe.page_length_policy(api='native', completion='success',
                         capacity=65536, information=information)
            self.assertEqual(result['code'], 'PAGE_BYTE_COUNT')

    def test_page_native_span_still_needs_parsing(self):
        result = probe.page_length_policy(api='native', completion='success', capacity=65536, information=106)
        self.assertEqual(result['span'], (0, 106))
        self.assertEqual(result['disposition'], 'STRUCTURAL_VALIDATION_REQUIRED')

    def test_page_zero_success_is_not_eof(self):
        result = probe.page_length_policy(api='native', completion='success', capacity=65536, information=0)
        self.assertEqual(result, {'status': 'INCOMPLETE', 'code': 'EMPTY_SUCCESS_NOT_END'})

    def test_page_explicit_native_end(self):
        result = probe.page_length_policy(api='native', completion='end', capacity=65536, information=0)
        self.assertEqual(result['disposition'], 'END_NO_RECORDS')
        result = probe.page_length_policy(api='native', completion='end', capacity=65536, information=106)
        self.assertEqual(result['code'], 'END_WITH_DATA')

    def test_page_pending_and_overflow_have_no_span(self):
        for completion, code in (('pending', 'COMPLETION_PENDING'), ('overflow', 'PAGE_TRUNCATED_NO_RETRY')):
            result = probe.page_length_policy(api='native', completion=completion, capacity=65536, information=106)
            self.assertEqual(result, {'status': 'INCOMPLETE', 'code': code})
            self.assertNotIn('span', result)

    def test_page_arguments_and_short_count(self):
        for capacity in (0, -1, True, 65537):
            result = probe.page_length_policy(api='native', completion='success', capacity=capacity, information=106)
            self.assertEqual(result['code'], 'PAGE_ARGUMENTS')
        result = probe.page_length_policy(api='native', completion='success', capacity=65536, information=105)
        self.assertEqual(result['code'], 'PAGE_SPAN_TOO_SHORT')

    def test_page_unknown_status_refused(self):
        result = probe.page_length_policy(api='native', completion='unrecognized', capacity=65536, information=106)
        self.assertEqual(result['code'], 'PAGE_COMPLETION')

    def test_special_names_are_explicit_audit_skips(self):
        for name, code in (('.', 'DOT_SELF'), ('..', 'DOT_PARENT')):
            result = probe.child_name_policy(name=name, kind='directory', attributes=0x10)
            self.assertEqual(result, {'status': 'VALIDATED', 'disposition': 'AUDIT_SKIP_NO_OPEN', 'code': code})

    def test_special_file_and_reparse_refused(self):
        result = probe.child_name_policy(name='..', kind='file', attributes=0x20)
        self.assertEqual(result['code'], 'SPECIAL_NOT_DIRECTORY')
        for attributes in (0x410, 0x50, 0x80000010):
            result = probe.child_name_policy(name='.', kind='directory', attributes=attributes)
            self.assertEqual(result['code'], 'CHILD_ATTRIBUTES')

    def test_child_type_mismatch_refused(self):
        result = probe.child_name_policy(name='.', kind='directory', attributes=0x20)
        self.assertEqual(result['code'], 'CHILD_TYPE')

    def test_dotlike_paths_not_special(self):
        for name in ('../x', './x', '..\\x', '...', '. ', 'A/B'):
            result = probe.child_name_policy(name=name, kind='directory', attributes=0x10)
            self.assertEqual(result['code'], 'CHILD_NAME')

    def test_regular_child_is_only_candidate(self):
        result = probe.child_name_policy(name='game.exe', kind='file', attributes=0x20)
        self.assertEqual(result['disposition'], 'OPEN_CANDIDATE_NOT_TRUSTED')

    def test_strict_binary_parser_still_rejects_dot_entries(self):
        for name in ('.', '..'):
            self.binary_refused(self.binary_record(name, attributes=0x10, size=0), 'INVALID_NAME')

    def binary_record(self, name='a', attributes=0x20, size=1, short=''):
        # Independent fixture layout from the documented x64 declaration;
        # never ask the parser for its offsets when constructing test bytes.
        encoded, alias = name.encode('utf-16-le'), short.encode('utf-16-le')
        data = bytearray(104 + len(encoded))
        struct.pack_into('<qq', data, 40, size, size)
        struct.pack_into('<II', data, 56, attributes, len(encoded))
        struct.pack_into('<b', data, 68, len(alias))
        data[70:70 + len(alias)] = alias
        struct.pack_into('<Q', data, 96, 0xfedcba9876543210)
        data[104:] = encoded
        return bytes(data)

    def binary_chain(self, records):
        result = bytearray()
        for index, record in enumerate(records):
            item = bytearray(record)
            if index < len(records) - 1:
                item.extend(b'\xa5' * (-len(item) % 8))
                struct.pack_into('<I', item, 0, len(item))
            result.extend(item)
        return bytes(result)

    def binary_refused(self, data, code):
        result = probe.parse_id_both_buffer(data)
        self.assertEqual(result['status'], 'REFUSED')
        self.assertEqual(result['error']['code'], code)
        self.assertNotIn('records', result)

    def test_binary_layout_derived_offsets(self):
        expected = {'NextEntryOffset': 0, 'FileIndex': 4, 'CreationTime': 8,
                    'LastAccessTime': 16, 'LastWriteTime': 24, 'ChangeTime': 32,
                    'EndOfFile': 40, 'AllocationSize': 48, 'FileAttributes': 56,
                    'FileNameLength': 60, 'EaSize': 64, 'ShortNameLength': 68,
                    'ShortName': 70, 'FileId': 96, 'FileName': 104}
        self.assertEqual(probe.id_both_layout(), (expected, 112))

    def test_binary_buffer_type(self):
        for value in (None, '', bytearray(106), memoryview(bytes(106)), []):
            self.binary_refused(value, 'BUFFER_TYPE')

    def test_binary_empty_and_short(self):
        for size in (0, 1, 4, 68, 96, 103, 104, 105):
            self.binary_refused(bytes(size), 'BUFFER_TOO_SHORT')

    def test_binary_single_terminal_record(self):
        result = probe.parse_id_both_buffer(self.binary_record('игра.exe', short='GAME.EXE'))
        self.assertEqual(result['status'], 'VALIDATED_BINARY_DESCRIPTIONS')
        self.assertEqual(result['records'][0], {'name': 'игра.exe', 'short_name': 'GAME.EXE',
                         'type': 'file', 'size': 1, 'attributes': 0x20,
                         'file_id': '1032547698badcfe'})

    def test_binary_multiple_records(self):
        data = self.binary_chain([self.binary_record('assets', 0x10, 0), self.binary_record('x')])
        result = probe.parse_id_both_buffer(data)
        self.assertEqual([r['name'] for r in result['records']], ['assets', 'x'])
        self.assertEqual(result['records'][0]['type'], 'directory')
        self.assertIsNone(result['records'][0]['size'])

    def test_binary_offsets(self):
        base = self.binary_chain([self.binary_record(), self.binary_record('b')])
        for step, code in ((8, 'OFFSET_IN_HEADER'), (113, 'OFFSET_ALIGNMENT'),
                           (224, 'OFFSET_BOUNDS'), (0xfffffff8, 'OFFSET_BOUNDS')):
            with self.subTest(step=step):
                data = bytearray(base)
                struct.pack_into('<I', data, 0, step)
                self.binary_refused(bytes(data), code)

    def test_binary_missing_terminator(self):
        data = bytearray(self.binary_record() + b'\0' * 6)
        struct.pack_into('<I', data, 0, len(data))
        self.binary_refused(bytes(data), 'MISSING_TERMINATOR')

    def test_binary_next_record_too_short(self):
        data = bytearray(self.binary_record() + b'\0' * 14)
        struct.pack_into('<I', data, 0, 112)
        self.binary_refused(bytes(data), 'NEXT_RECORD_TOO_SHORT')

    def test_binary_name_overlaps_next_record(self):
        data = bytearray(self.binary_chain([self.binary_record(), self.binary_record('b')]))
        struct.pack_into('<I', data, 60, 20)
        self.binary_refused(bytes(data), 'NAME_BOUNDS')

    def test_binary_truncated_name(self):
        data = bytearray(self.binary_record())
        struct.pack_into('<I', data, 60, 4)
        self.binary_refused(bytes(data), 'NAME_BOUNDS')

    def test_binary_name_lengths(self):
        for length, code in ((0, 'NAME_LENGTH'), (1, 'NAME_LENGTH'),
                             (511, 'NAME_LENGTH'), (512, 'NAME_LIMIT'),
                             (0xffffffff, 'NAME_LENGTH')):
            data = bytearray(self.binary_record())
            struct.pack_into('<I', data, 60, length)
            self.binary_refused(bytes(data), code)

    def test_binary_invalid_utf16(self):
        for encoded in (b'\0\xd8', b'\0\xdc'):
            self.binary_refused(self.binary_record()[:104] + encoded, 'INVALID_UTF16')

    def test_binary_bad_names(self):
        for name in ('.', '..', '/a', 'a/b', 'a\\b', 'C:a', 'NUL', 'a.', 'a ', '\0'):
            with self.subTest(name=name):
                self.binary_refused(self.binary_record(name), 'INVALID_NAME')

    def test_binary_short_name_lengths(self):
        for length in (-1, 1, 25, 127):
            data = bytearray(self.binary_record())
            struct.pack_into('<b', data, 68, length)
            self.binary_refused(bytes(data), 'SHORT_NAME_LENGTH')

    def test_binary_invalid_short_name_utf16(self):
        data = bytearray(self.binary_record())
        struct.pack_into('<b', data, 68, 2)
        data[70:72] = b'\0\xd8'
        self.binary_refused(bytes(data), 'INVALID_UTF16')

    def test_binary_forbidden_attributes(self):
        for attributes in (0x400, 0x40, 0x80000000, 0xffffffff, 0x90):
            self.binary_refused(self.binary_record(attributes=attributes), 'ATTRIBUTES_POLICY')

    def test_binary_negative_sizes(self):
        for offset in (40, 48):
            data = bytearray(self.binary_record())
            struct.pack_into('<q', data, offset, -1)
            self.binary_refused(bytes(data), 'NEGATIVE_SIZE')

    def test_binary_entry_size(self):
        self.binary_refused(self.binary_record(size=probe.MAX_ENTRY + 1), 'ENTRY_SIZE')

    def test_binary_record_count(self):
        data = self.binary_chain([self.binary_record(str(i)) for i in range(probe.MAX_DIR_RECORDS + 1)])
        self.binary_refused(data, 'RECORD_LIMIT')

    def test_binary_buffer_limit(self):
        self.binary_refused(bytes(probe.MAX_DIR_BUFFER + 1), 'BUFFER_LIMIT')

    def test_binary_total_name_limit(self):
        data = self.binary_chain([self.binary_record(str(i) + 'x' * 200) for i in range(21)])
        self.binary_refused(data, 'NAMES_TOTAL_LIMIT')

    def test_binary_duplicate_and_no_partial_records(self):
        self.binary_refused(self.binary_chain([self.binary_record('a'), self.binary_record('A')]),
                            'DUPLICATE_NAME')

    def test_binary_terminal_padding_policy(self):
        for count in range(8):
            result = probe.parse_id_both_buffer(self.binary_record() + b'\xa5' * count)
            self.assertEqual(result['status'], 'VALIDATED_BINARY_DESCRIPTIONS')
        self.binary_refused(self.binary_record() + b'\0' * 8, 'TERMINAL_SPAN_POLICY')

    def test_binary_unused_padding_not_required_zero(self):
        data = bytearray(self.binary_record())
        data[69] = 0xff
        data[94:96] = b'\xfe\xff'
        result = probe.parse_id_both_buffer(bytes(data))
        self.assertEqual(result['status'], 'VALIDATED_BINARY_DESCRIPTIONS')

    def test_binary_opaque_field_boundaries(self):
        data = bytearray(self.binary_record())
        for offset in (4, 64):
            struct.pack_into('<I', data, offset, 0xffffffff)
        for offset in (8, 16, 24, 32, 96):
            struct.pack_into('<Q', data, offset, 0xffffffffffffffff)
        result = probe.parse_id_both_buffer(bytes(data))
        self.assertEqual(result['status'], 'VALIDATED_BINARY_DESCRIPTIONS')
        self.assertEqual(result['records'][0]['file_id'], 'ffffffffffffffff')

    def test_binary_deterministic_random_bytes(self):
        import random
        rng = random.Random(1741)
        for i in range(250):
            data = bytes(rng.getrandbits(8) for _ in range(rng.randrange(300)))
            result = probe.parse_id_both_buffer(data)
            self.assertIn(result['status'], ('REFUSED', 'VALIDATED_BINARY_DESCRIPTIONS'))
            if result['status'] == 'REFUSED':
                self.assertNotIn('records', result)
                self.assertIsInstance(result['error']['offset'], int)

    def test_binary_record_count_boundary(self):
        data = self.binary_chain([self.binary_record(str(i)) for i in range(probe.MAX_DIR_RECORDS)])
        result = probe.parse_id_both_buffer(data)
        self.assertEqual(len(result['records']), probe.MAX_DIR_RECORDS)

    def test_binary_name_total_boundary(self):
        records = [self.binary_record(f'{i:02}' + 'x' * 253) for i in range(16)]
        records.append(self.binary_record('name1234' * 2))  # 16*510 + 32 = 8192
        result = probe.parse_id_both_buffer(self.binary_chain(records))
        self.assertEqual(result['name_bytes'], probe.MAX_DIR_NAME_BYTES)
        self.binary_refused(self.binary_chain(records + [self.binary_record('j')]), 'NAMES_TOTAL_LIMIT')

    def test_binary_unicode_preserved(self):
        name = 'Игpa_\U0001f600.exe'
        result = probe.parse_id_both_buffer(self.binary_record(name))
        self.assertEqual(result['records'][0]['name'], name)

    def test_binary_short_name_invalid_path(self):
        self.binary_refused(self.binary_record(short='../a'), 'INVALID_NAME')

    def test_binary_second_record_failure_is_structured(self):
        good = self.binary_record('good')
        bad = self.binary_record('bad', attributes=0x400)
        result = probe.parse_id_both_buffer(self.binary_chain([good, bad]))
        self.assertEqual(result['error'], {'code': 'ATTRIBUTES_POLICY', 'offset': 112})
        self.assertNotIn('records', result)

    def test_binary_unexpected_exception_propagates(self):
        from unittest.mock import patch
        with patch.object(probe.struct, 'unpack_from', side_effect=RuntimeError('unexpected')):
            with self.assertRaisesRegex(RuntimeError, 'unexpected'):
                probe.parse_id_both_buffer(self.binary_record())

    def description(self, path='a', kind='file', size=0):
        return {'path': path, 'type': kind, 'size': size}

    def assert_refused(self, records, code):
        result = probe.parse_descriptions(records)
        self.assertEqual(result['status'], 'REFUSED')
        self.assertEqual(result['error']['code'], code)
        self.assertNotIn('inventory', result)

    def test_descriptions_success_and_order(self):
        records = [self.description('z'), self.description('assets/a', size=5),
                   self.description('assets', 'directory', None)]
        result = probe.parse_descriptions(records)
        self.assertEqual(result['status'], 'VALIDATED_DESCRIPTIONS')
        self.assertEqual(result['inventory'], (('assets', 'directory', None),
                         ('assets/a', 'file', 5), ('z', 'file', 0)))
        self.assertEqual(result, probe.parse_descriptions(list(reversed(records))))
        self.assertEqual((result['file_count'], result['total_bytes']), (2, 5))

    def test_descriptions_bad_names(self):
        for name in ('', '/a', '../a', '.', '..', 'a/./b', 'a/../b', 'a//b',
                     'a\\b', '\\server\\share', 'C:a', 'C:/a', 'a:stream',
                     'CON', 'prn.txt', 'COM1', 'LPT¹.txt', 'a.', 'a ', 'a\x00b',
                     'a\nb', 'a' * 256, '\ud800'):
            with self.subTest(name=repr(name)):
                self.assert_refused([self.description(name)], 'UNSAFE_PATH')

    def test_descriptions_path_limits(self):
        self.assert_refused([self.description('/'.join(['a'] * 33))], 'PATH_LIMIT')
        self.assert_refused([self.description('/'.join(['\U0001f600' * 120] * 5))], 'PATH_LIMIT')
        self.assert_refused([self.description('a' * 1025)], 'UNSAFE_PATH')

    def test_descriptions_duplicates(self):
        for first, second in ((self.description(), self.description()),
                              (self.description('A'), self.description('a')),
                              (self.description(), self.description(size=1)),
                              (self.description(), self.description('a', 'directory', None))):
            with self.subTest(second=second):
                self.assert_refused([first, second], 'DUPLICATE_PATH')

    def test_descriptions_directory_case_conflict(self):
        self.assert_refused([self.description('Assets/a'), self.description('assets/b')], 'CASE_ALIAS')

    def test_descriptions_file_parent_both_orders(self):
        records = [self.description('a'), self.description('a/b')]
        for values in (records, list(reversed(records))):
            self.assert_refused(values, 'FILE_PARENT_CONFLICT')

    def test_descriptions_implicit_parent(self):
        result = probe.parse_descriptions([self.description('assets/a')])
        self.assertEqual(result['inventory'], (('assets/a', 'file', 0),))

    def test_descriptions_negative_and_noninteger_size(self):
        for size in (-1, True, 1.5, '1', None):
            self.assert_refused([self.description(size=size)], 'FILE_SIZE')

    def test_descriptions_directory_size_contradiction(self):
        for size in (-1, 0, True):
            self.assert_refused([self.description('a', 'directory', size)], 'DIRECTORY_SIZE')

    def test_descriptions_unknown_type(self):
        for kind in ('symlink', 'junction', 'FILE', '', None, 1):
            self.assert_refused([self.description(kind=kind)], 'ENTRY_TYPE')

    def test_descriptions_schema_and_input_type(self):
        for records in (None, {}, 'a', iter(())):
            self.assert_refused(records, 'INPUT_TYPE')
        for record in ({}, {'path': 'a', 'type': 'file', 'size': 0, 'unknown': 1}, None):
            self.assert_refused([record], 'RECORD_SCHEMA')
        self.assert_refused([self.description(123)], 'PATH_TYPE')

    def test_descriptions_record_count(self):
        self.assert_refused([], 'RECORD_COUNT')
        self.assert_refused([None] * (probe.MAX_TREE_NODES + 1), 'RECORD_COUNT')

    def test_descriptions_file_count(self):
        self.assert_refused([self.description(str(i)) for i in range(probe.MAX_ENTRIES + 1)], 'FILE_COUNT')

    def test_descriptions_entry_and_total_sizes(self):
        self.assert_refused([self.description(size=probe.MAX_ENTRY + 1)], 'ENTRY_SIZE')
        self.assert_refused([self.description(str(i), size=probe.MAX_ENTRY) for i in range(3)], 'TOTAL_SIZE')

    def test_descriptions_unicode_preserved_no_case_conversion(self):
        result = probe.parse_descriptions([self.description('Ресурсы/игра.exe')])
        self.assertEqual(result['inventory'][0][0], 'Ресурсы/игра.exe')

    def test_descriptions_no_partial_inventory_and_error_index(self):
        result = probe.parse_descriptions([self.description('valid'), self.description('../bad')])
        self.assertEqual(result['error'], {'code': 'UNSAFE_PATH', 'index': 1})
        self.assertNotIn('inventory', result)

    def test_descriptions_unexpected_error_not_hidden(self):
        from unittest.mock import patch
        with patch.object(probe, 'relative_name', side_effect=RuntimeError('unexpected')):
            with self.assertRaisesRegex(RuntimeError, 'unexpected'):
                probe.parse_descriptions([self.description()])

    def test_tree_parent_before_child(self):
        ledger = probe.TreeLedger()
        ledger.admit('assets', directory=True, size=0, attributes=0x10)
        ledger.admit('assets/a', directory=False, size=3, attributes=0)
        self.assertEqual((ledger.files, ledger.total), (1, 3))

    def test_tree_rejection_poisoned_session(self):
        ledger = probe.TreeLedger()
        with self.assertRaisesRegex(probe.Refusal, '^TREE_PARENT$'):
            ledger.admit('missing/a', directory=False, size=1, attributes=0)
        with self.assertRaisesRegex(probe.Refusal, '^TREE_SESSION_FAILED$'):
            ledger.admit('a', directory=False, size=1, attributes=0)
        self.assertEqual(ledger.nodes, {})

    def test_tree_parent_case_alias(self):
        ledger = probe.TreeLedger()
        ledger.admit('Assets', directory=True, size=0, attributes=0x10)
        with self.assertRaisesRegex(probe.Refusal, '^TREE_PARENT$'):
            ledger.admit('assets/a', directory=False, size=1, attributes=0)

    def test_tree_file_cannot_be_parent(self):
        ledger = probe.TreeLedger()
        ledger.admit('a', directory=False, size=1, attributes=0)
        with self.assertRaisesRegex(probe.Refusal, '^TREE_PARENT$'):
            ledger.admit('a/b', directory=False, size=1, attributes=0)

    def test_tree_depth_limit(self):
        with self.assertRaisesRegex(probe.Refusal, '^TREE_PATH_LIMIT$'):
            probe.TreeLedger().admit('/'.join(['a'] * (probe.MAX_DEPTH + 1)),
                                    directory=False, size=0, attributes=0)

    def test_tree_utf16_total_length(self):
        name = '/'.join(['\U0001f600' * 120] * 5)
        with self.assertRaisesRegex(probe.Refusal, '^TREE_PATH_LIMIT$'):
            probe.TreeLedger().admit(name, directory=False, size=0, attributes=0)

    def test_tree_node_bound(self):
        ledger = probe.TreeLedger()
        for i in range(probe.MAX_TREE_NODES):
            ledger.admit('d' + str(i), directory=True, size=0, attributes=0x10)
        with self.assertRaisesRegex(probe.Refusal, '^TREE_NODE_LIMIT$'):
            ledger.admit('extra', directory=True, size=0, attributes=0x10)

    def test_tree_file_bound(self):
        ledger = probe.TreeLedger()
        for i in range(probe.MAX_ENTRIES):
            ledger.admit('f' + str(i), directory=False, size=0, attributes=0)
        with self.assertRaisesRegex(probe.Refusal, '^TREE_SIZE_LIMIT$'):
            ledger.admit('extra', directory=False, size=0, attributes=0)

    def test_tree_total_bytes_bound(self):
        ledger = probe.TreeLedger()
        for i in range(2):
            ledger.admit('f' + str(i), directory=False, size=probe.MAX_ENTRY, attributes=0)
        with self.assertRaisesRegex(probe.Refusal, '^TREE_SIZE_LIMIT$'):
            ledger.admit('extra', directory=False, size=1, attributes=0)

    def test_tree_object_rejections(self):
        for attributes, disk, links, reason in (
            (0x400, True, 1, 'TREE_REPARSE_OR_NON_DISK'),
            (0, False, 1, 'TREE_REPARSE_OR_NON_DISK'),
            (0x10, True, 1, 'TREE_OBJECT_TYPE'),
            (0, True, 2, 'TREE_HARDLINK')):
            with self.subTest(reason=reason), self.assertRaisesRegex(probe.Refusal, '^' + reason + '$'):
                probe.TreeLedger().admit('a', directory=False, size=0,
                                         attributes=attributes, disk=disk, links=links)

    def test_tree_duplicate(self):
        ledger = probe.TreeLedger()
        ledger.admit('a', directory=False, size=0, attributes=0)
        with self.assertRaisesRegex(probe.Refusal, '^TREE_DUPLICATE$'):
            ledger.admit('A', directory=False, size=0, attributes=0)

    def test_supervisor_requires_owned_handle(self):
        self.assertEqual(probe.worker_action(owned_handle=False, exited=False,
                         deadline_reached=True, termination_requested=False), 'BLOCKED_NO_OWNED_HANDLE')

    def test_supervisor_timeout_is_not_completion(self):
        self.assertEqual(probe.worker_action(owned_handle=True, exited=False,
                         deadline_reached=True, termination_requested=False),
                         'REQUEST_TERMINATION_OF_OWNED_CHILD')
        self.assertEqual(probe.worker_action(owned_handle=True, exited=False,
                         deadline_reached=True, termination_requested=True),
                         'WAIT_BOUNDED_FOR_TERMINATION')

    def test_worker_incomplete_never_passes(self):
        self.assertEqual(probe.assess_worker_result(exited=True, exit_code=0,
                         timed_out=False, report_complete=False), 'FAIL_INCOMPLETE_OR_ERROR')
        self.assertEqual(probe.assess_worker_result(exited=False, exit_code=None,
                         timed_out=False, report_complete=True), 'BLOCKED_WORKER_NOT_EXITED')

    def test_timeout_overrides_success_report(self):
        self.assertEqual(probe.assess_worker_result(exited=True, exit_code=0,
                         timed_out=True, report_complete=True), 'FAIL_TIMEOUT')

    def test_expected_reason_must_match_exactly(self):
        self.assertEqual(probe.assess_worker_result(exited=True, exit_code=0,
                         timed_out=False, report_complete=True,
                         expected_reason='TREE_PARENT', reported_reason='TREE_DUPLICATE'),
                         'FAIL_UNEXPECTED_REFUSAL')

    def test_report_alone_never_proves_filesystem(self):
        for expected, reported in ((None, None), ('TREE_PARENT', 'TREE_PARENT')):
            self.assertEqual(probe.assess_worker_result(exited=True, exit_code=0,
                             timed_out=False, report_complete=True,
                             expected_reason=expected, reported_reason=reported),
                             'NOT TESTED_FILESYSTEM_EVIDENCE_REQUIRED')

    def test_parser_only(self):
        self.assertEqual(probe.parser().parse_args(['preflight']).command, 'preflight')
        for case in probe.CASES:
            self.assertEqual(probe.parser().parse_args(['run-case', case]).case, case)

    def test_bad_paths(self):
        for name in ('../a', '/a', 'a//b', 'a/./b', 'C:/a', 'a:b', 'a\\b',
                     'CON', 'aux.txt', 'COM1', 'LPT¹', 'a.', 'a ', 'a/../b', 'a\x00b'):
            with self.subTest(name=name), self.assertRaisesRegex(probe.Refusal, 'UNSAFE_PATH'):
                probe.relative_name(name)

    def test_unicode_name(self):
        self.assertEqual(probe.relative_name('ресурсы/игра.exe'), ('ресурсы', 'игра.exe'))

    def test_utf16_component_limit(self):
        with self.assertRaises(probe.Refusal):
            probe.relative_name('😀' * 128)

    def test_aliases(self):
        for names, reason in ((['a', 'A'], 'DUPLICATE_PATH'),
                              (['a/x', 'A/y'], 'CASE_ALIAS'),
                              (['a', 'a/b'], 'PARENT_CONFLICT')):
            with self.subTest(names=names), self.assertRaisesRegex(probe.Refusal, reason):
                probe.check_names(names)

    def test_hash(self):
        self.assertEqual(probe.hash_stream(io.BytesIO(b'abc'), 3)[0], 3)

    def test_hash_overflow(self):
        with self.assertRaisesRegex(probe.Refusal, 'BYTE_LIMIT'):
            probe.hash_stream(io.BytesIO(b'ab'), 1)

    def test_hash_unexpected_error(self):
        class Broken:
            def read(self, size):
                raise OSError('unexpected')
        with self.assertRaisesRegex(OSError, 'unexpected'):
            probe.hash_stream(Broken(), 10)

    def test_read_budget(self):
        budget = probe.Budget(maximum=1)
        budget.charge(1)
        with self.assertRaisesRegex(probe.Refusal, 'READ_LIMIT'):
            budget.charge(1)

    def test_deadline_before_read(self):
        ticks = iter((0, 2))
        budget = probe.Budget(seconds=1, clock=lambda: next(ticks))
        with self.assertRaisesRegex(probe.Refusal, 'TIME_LIMIT'):
            probe.hash_stream(io.BytesIO(b'a'), 1, budget)

    def test_bounded_reader_preallocation_guard(self):
        view = probe.BoundedReader(io.BytesIO(b'abc'), probe.Budget(maximum=1))
        with self.assertRaisesRegex(probe.Refusal, 'READ_REQUEST_LIMIT'):
            view.read(2)
        self.assertEqual(view.tell(), 0)

    def entries(self):
        entries = []
        for name in sorted(probe.REQUIRED):
            item = zipfile.ZipInfo(probe.PREFIX + name)
            item.file_size = item.compress_size = 0
            entries.append(item)
        return entries

    def test_valid_entry_metadata(self):
        self.assertEqual(set(probe.validate_entries(self.entries())), probe.REQUIRED)

    def test_declared_entry_size_limit(self):
        entries = self.entries()
        entries[0].file_size = probe.MAX_ENTRY + 1
        with self.assertRaisesRegex(probe.Refusal, 'ENTRY_SIZE'):
            probe.validate_entries(entries)

    def test_total_size_limit(self):
        entries = self.entries()
        for entry in entries:
            entry.file_size = probe.MAX_ENTRY
        with self.assertRaisesRegex(probe.Refusal, 'TOTAL_SIZE'):
            probe.validate_entries(entries)

    def test_entry_count_limit(self):
        with self.assertRaisesRegex(probe.Refusal, 'ENTRY_COUNT'):
            probe.validate_entries([None] * (probe.MAX_ENTRIES + 1))

    def test_reparse_attribute(self):
        entries = self.entries()
        entries[0].external_attr |= 0x400
        with self.assertRaisesRegex(probe.Refusal, 'ZIP_ENTRY_TYPE'):
            probe.validate_entries(entries)

    def test_missing_required(self):
        with self.assertRaisesRegex(probe.Refusal, 'REQUIRED_FILE_MISSING'):
            probe.validate_entries(self.entries()[1:])

    def test_nul_name_rejected(self):
        entries = self.entries()
        entries[0] = zipfile.ZipInfo(probe.PREFIX + 'NEXUS.exe\x00suffix')
        with self.assertRaisesRegex(probe.Refusal, 'ZIP_NAME'):
            probe.validate_entries(entries)

    def test_symlink_entry(self):
        entries = self.entries()
        entries[0].external_attr = 0o120777 << 16
        with self.assertRaisesRegex(probe.Refusal, 'ZIP_ENTRY_TYPE'):
            probe.validate_entries(entries)

    def test_encrypted_entry(self):
        entries = self.entries()
        entries[0].flag_bits = 1
        with self.assertRaisesRegex(probe.Refusal, 'ZIP_ENTRY_TYPE'):
            probe.validate_entries(entries)

    def test_structure_checked_before_decompression(self):
        entries = self.entries()
        entries[0].file_size = probe.MAX_ENTRY + 1
        class Archive:
            def infolist(self):
                return entries
            def open(self, entry):
                raise AssertionError('must reject before reading entry')
        with self.assertRaisesRegex(probe.Refusal, 'ENTRY_SIZE'):
            probe.inventory_from_zip(Archive())

    def test_memory_zip_inventory(self):
        data = io.BytesIO()
        with zipfile.ZipFile(data, 'w') as archive:
            for name in probe.REQUIRED:
                archive.writestr(probe.PREFIX + name, b'abc')
        data.seek(0)
        view = probe.BoundedReader(data, probe.Budget())
        count = probe.check_eocd(view, len(data.getvalue()))
        self.assertEqual(count, len(probe.REQUIRED))
        with zipfile.ZipFile(view) as archive:
            inventory = probe.inventory_from_zip(archive)
        self.assertEqual(set(inventory), probe.REQUIRED)
        self.assertTrue(all(size == 3 for size, digest in inventory.values()))

    def test_eocd_rejects_large_central_before_read(self):
        raw = b'PK\x03\x04' + struct.pack('<4s4H2LH', b'PK\x05\x06', 0, 0, 1, 1,
                                            probe.MAX_CENTRAL + 1, 4, 0)
        with self.assertRaisesRegex(probe.Refusal, 'ZIP_CENTRAL_LIMIT'):
            probe.check_eocd(io.BytesIO(raw), len(raw))

    def test_eocd_rejects_zip64(self):
        raw = b'PK\x03\x04' + struct.pack('<4s4H2LH', b'PK\x05\x06', 0, 0, 65535, 65535, 0, 4, 0)
        with self.assertRaisesRegex(probe.Refusal, 'ZIP_UNSUPPORTED_LAYOUT'):
            probe.check_eocd(io.BytesIO(raw), len(raw))
