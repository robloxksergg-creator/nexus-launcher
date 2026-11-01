import json
import unittest
from nexus_launcher.dependency_versions import check_version


class VersionPredicateTests(unittest.TestCase):
    def fabric(self, actual, expression):
        return check_version(actual,json.dumps(expression),'fabric')

    def test_fabric_numeric_operators(self):
        for version, condition, expected in [
            ('1.10','>1.2','MATCH'),('1.2','>1.10','MISMATCH'),('1.2.0','=1.2','MATCH'),
            ('1.2','>=1.2 <2','MATCH'),('2.0','>=1.2 <2','MISMATCH'),
            ('1','<=1.0.0','MATCH'),('1','<1.0.0','MISMATCH'),('1.0.0.2','>1','MATCH')]:
            with self.subTest(version=version,condition=condition):self.assertEqual(self.fabric(version,condition),expected)

    def test_fabric_arrays_are_or(self):
        self.assertEqual(self.fabric('2.0',['<1','>=2']),'MATCH')
        self.assertEqual(self.fabric('1.5',['<1','>=2']),'MISMATCH')
        self.assertEqual(self.fabric('2.0',['*','garbage']),'UNKNOWN')

    def test_fabric_wildcard_prefixes(self):
        for condition in ('1.x','1.X.*','1.*'):
            self.assertEqual(self.fabric('1.99',condition),'MATCH')
            self.assertEqual(self.fabric('2.0',condition),'MISMATCH')
        self.assertEqual(self.fabric('1.2.99','1.2.x'),'MATCH')
        self.assertEqual(self.fabric('1.3','1.2.x'),'MISMATCH')
        self.assertEqual(self.fabric('1.2','>=1.x'),'UNKNOWN')

    def test_fabric_caret_is_not_npm_zero_major(self):
        self.assertEqual(self.fabric('0.9','^0.2.3'),'MATCH')
        self.assertEqual(self.fabric('1.0','^0.2.3'),'MISMATCH')
        self.assertEqual(self.fabric('1.8','~1.2.3'),'MISMATCH')
        self.assertEqual(self.fabric('1.2.9','~1.2.3'),'MATCH')

    def test_build_metadata_is_ignored_only_for_fabric(self):
        self.assertEqual(self.fabric('1.2.0+mc1.21.1','>=1.2'),'MATCH')
        self.assertEqual(check_version('1.2.0+build','[1.2,2)','maven'),'UNKNOWN')

    def test_unknown_versions_are_not_matched_even_by_wildcard(self):
        for actual in ('dev','${file.jarVersion}','1.0-rc1','24w01a','01.2','١.٢','1.0+',None):
            self.assertEqual(self.fabric(actual,'*'),'UNKNOWN')

    def test_maven_numeric_bounds_and_unions(self):
        for actual, expression, expected in [
            ('1.2','[1,2)','MATCH'),('2','[1,2)','MISMATCH'),
            ('1','(1,2]','MISMATCH'),('2','(1,2]','MATCH'),
            ('1.0.0','[1]','MATCH'),('1.1','(,1]','MISMATCH'),
            ('3','[2,)','MATCH'),('1.1','(,1],[1.2,)','MISMATCH'),
            ('1.2','(,1],[1.2,)','MATCH'),('1.10','[1.2,2)','MATCH')]:
            with self.subTest(actual=actual,expression=expression):self.assertEqual(check_version(actual,expression,'maven'),expected)

    def test_maven_bare_soft_version_is_not_exact(self):
        self.assertEqual(check_version('1.0','1.0','maven'),'UNKNOWN')
        self.assertEqual(check_version('2.0','1.0','maven'),'UNKNOWN')

    def test_invalid_maven_ranges_are_unknown(self):
        for expression in ('[2,1]','[1,1)','(,)','[1,2','[1,2),','[1,2)||[3,4)','[1,2],[x,4]','[1.0-beta,2]'):
            self.assertEqual(check_version('1.5',expression,'maven'),'UNKNOWN')

    def test_invalid_fabric_ranges_are_unknown(self):
        for expression in ('','>=bad','>= 1.0','1 || 2','==1','1.2.3.x','~1'):
            self.assertEqual(self.fabric('1.2',expression),'UNKNOWN')
        for expression in ('[]','null','["*",12]','{"version":"*"}'):
            self.assertEqual(check_version('1',expression,'fabric'),'UNKNOWN')

    def test_bounds_and_unknown_syntax(self):
        self.assertEqual(check_version('1','x'*4097,'fabric'),'UNKNOWN')
        self.assertEqual(check_version('1','[1]','other'),'UNKNOWN')
        self.assertEqual(self.fabric('1',['*']*33),'UNKNOWN')
        self.assertEqual(self.fabric('1',' '.join(['*']*17)),'UNKNOWN')

    def test_deep_json_is_unknown_not_a_parser_failure(self):
        self.assertEqual(check_version('1','['*1500+'"*"'+']'*1500,'fabric'),'UNKNOWN')


if __name__=='__main__':unittest.main()
