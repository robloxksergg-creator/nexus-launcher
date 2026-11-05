// Narrow UAC helper. No Python, package loading, shell commands or child process.
// Only atomically creates one new directory and grants Modify to one account SID.
#define WIN32_LEAN_AND_MEAN
#include <windows.h>
#include <winternl.h>
#include <aclapi.h>
#include <sddl.h>
#include <shellapi.h>
#include <string>
#include <vector>
#include <cwctype>
#include <cstring>

struct Handle {
    HANDLE value = INVALID_HANDLE_VALUE;
    explicit Handle(HANDLE h) : value(h) {}
    Handle(const Handle&) = delete;
    Handle& operator=(const Handle&) = delete;
    ~Handle() { if (value != INVALID_HANDLE_VALUE && value != nullptr) CloseHandle(value); }
};

static bool component_ok(const std::wstring& name) {
    if (name.empty() || name.size() > 255 || name.back() == L'.' || name.back() == L' ') return false;
    for (wchar_t c : name) if (c < 32 || std::wstring(L"<>:\"/|?*").find(c) != std::wstring::npos) return false;
    std::wstring stem = name.substr(0, name.find(L'.'));
    for (wchar_t& c : stem) c = static_cast<wchar_t>(towupper(c));
    if (stem == L"CON" || stem == L"PRN" || stem == L"AUX" || stem == L"NUL") return false;
    if (stem.size() == 4 && (stem.substr(0, 3) == L"COM" || stem.substr(0, 3) == L"LPT") &&
        ((stem[3] >= L'1' && stem[3] <= L'9') || stem[3] == L'\u00b9' || stem[3] == L'\u00b2' || stem[3] == L'\u00b3')) return false;
    return true;
}

static int prepare(const std::wstring& path, const std::wstring& sid_text) {
    if (path.size() < 4 || path.size() > 32760 || !iswalpha(path[0]) || path[1] != L':' || path[2] != L'\\') return 2;
    std::vector<std::wstring> parts;
    size_t start = 3;
    while (start < path.size()) {
        const size_t end = path.find(L'\\', start);
        auto part = path.substr(start, end == std::wstring::npos ? end : end - start);
        if (!component_ok(part)) return 2;
        parts.push_back(part);
        if (end == std::wstring::npos) break;
        start = end + 1;
        if (start == path.size()) return 2;
    }
    if (parts.empty() || GetDriveTypeW(path.substr(0, 3).c_str()) == DRIVE_REMOTE) return 2;
    PSID sid = nullptr;
    if (!ConvertStringSidToSidW(sid_text.c_str(), &sid)) return 2;
    struct SidFree { PSID p; ~SidFree() { LocalFree(p); } } sid_free{sid};
    SID_IDENTIFIER_AUTHORITY authority = SECURITY_NT_AUTHORITY;
    if (!IsValidSid(sid) || *GetSidSubAuthorityCount(sid) != 5 ||
        memcmp(GetSidIdentifierAuthority(sid), &authority, sizeof(authority)) != 0 ||
        *GetSidSubAuthority(sid, 0) != 21) return 2;
    std::vector<HANDLE> pins;
    struct PinsClose { std::vector<HANDLE>& v; ~PinsClose() { for (auto h : v) CloseHandle(h); } } close{pins};
    std::wstring current = path.substr(0, 3);
    for (size_t i = 0; i < parts.size(); ++i) {
        // Parent components are opened without following reparse points and
        // without DELETE sharing. Hold every handle until the ACL is complete.
        auto h = CreateFileW((L"\\\\?\\" + current).c_str(), FILE_LIST_DIRECTORY | FILE_READ_ATTRIBUTES,
            FILE_SHARE_READ | FILE_SHARE_WRITE, nullptr, OPEN_EXISTING,
            FILE_FLAG_BACKUP_SEMANTICS | FILE_FLAG_OPEN_REPARSE_POINT, nullptr);
        if (h == INVALID_HANDLE_VALUE) return 3;
        pins.push_back(h);
        FILE_ATTRIBUTE_TAG_INFO info{};
        if (!GetFileInformationByHandleEx(h, FileAttributeTagInfo, &info, static_cast<DWORD>(sizeof(info))) ||
            !(info.FileAttributes & FILE_ATTRIBUTE_DIRECTORY) || (info.FileAttributes & FILE_ATTRIBUTE_REPARSE_POINT)) return 3;
        if (i + 1 < parts.size()) {
            if (current.back() != L'\\') current += L'\\';
            current += parts[i];
        }
    }
    auto& leaf = parts.back();
    UNICODE_STRING name{};
    name.Buffer = const_cast<PWSTR>(leaf.c_str());
    name.Length = static_cast<USHORT>(leaf.size() * sizeof(wchar_t));
    name.MaximumLength = name.Length;
    OBJECT_ATTRIBUTES attributes{};
    attributes.Length = static_cast<ULONG>(sizeof(attributes));
    attributes.RootDirectory = pins.back();
    attributes.ObjectName = &name;
    attributes.Attributes = OBJ_CASE_INSENSITIVE;
    IO_STATUS_BLOCK io{};
    HANDLE created = INVALID_HANDLE_VALUE;
    // FILE_CREATE is exclusive. Atomic creation returns the pinned handle;
    // there is no path-based mkdir/open substitution window.
    const NTSTATUS status = NtCreateFile(&created, FILE_LIST_DIRECTORY | FILE_READ_ATTRIBUTES | READ_CONTROL | WRITE_DAC | SYNCHRONIZE,
        &attributes, &io, nullptr, FILE_ATTRIBUTE_NORMAL, FILE_SHARE_READ | FILE_SHARE_WRITE,
        2 /* FILE_CREATE */, 1 /* FILE_DIRECTORY_FILE */ | 0x20 /* FILE_SYNCHRONOUS_IO_NONALERT */ | 0x00200000 /* FILE_OPEN_REPARSE_POINT */,
        nullptr, 0);
    if (status < 0) return 4;
    Handle directory(created);
    PACL original = nullptr;
    PSECURITY_DESCRIPTOR descriptor = nullptr;
    if (GetSecurityInfo(created, SE_FILE_OBJECT, DACL_SECURITY_INFORMATION, nullptr, nullptr,
                        &original, nullptr, &descriptor) != ERROR_SUCCESS) return 5;
    struct DescriptorFree { PSECURITY_DESCRIPTOR p; ~DescriptorFree() { LocalFree(p); } } free_descriptor{descriptor};
    EXPLICIT_ACCESSW access{};
    access.grfAccessPermissions = FILE_GENERIC_READ | FILE_GENERIC_WRITE | FILE_GENERIC_EXECUTE | DELETE;
    access.grfAccessMode = SET_ACCESS;
    access.grfInheritance = SUB_CONTAINERS_AND_OBJECTS_INHERIT;
    access.Trustee.TrusteeForm = TRUSTEE_IS_SID;
    access.Trustee.TrusteeType = TRUSTEE_IS_USER;
    access.Trustee.ptstrName = static_cast<LPWSTR>(sid);
    PACL updated = nullptr;
    if (SetEntriesInAclW(1, &access, original, &updated) != ERROR_SUCCESS) return 5;
    const DWORD result = SetSecurityInfo(created, SE_FILE_OBJECT, DACL_SECURITY_INFORMATION,
                                        nullptr, nullptr, updated, nullptr);
    LocalFree(updated);
    return result == ERROR_SUCCESS ? 0 : 5;
}

int WINAPI wWinMain(HINSTANCE, HINSTANCE, PWSTR, int) {
    int count = 0;
    auto args = CommandLineToArgvW(GetCommandLineW(), &count);
    if (!args) return 2;
    int result = 2;
    try { if (count == 3) result = prepare(args[1], args[2]); } catch (...) { result = 6; }
    LocalFree(args);
    return result;
}
