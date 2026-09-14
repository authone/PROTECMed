// Artifact serialization with the filesystem rules of blueprint 2.7 / 2.8:
// size-limited reads, no symlink following, create-new writes, owner-only modes,
// atomic rename, and a private-directory check before a secret share is written.
#include "worker.h"

#include "ciphertext-ser.h"
#include "cryptocontext-ser.h"
#include "key/key-ser.h"
#include "scheme/bgvrns/bgvrns-ser.h"

#include <fcntl.h>
#include <sys/stat.h>
#include <unistd.h>

#include <cerrno>
#include <cstdio>
#include <sstream>
#include <string>

namespace protecmed {

using namespace lbcrypto;

namespace {

int OpenForRead(const std::string& path) {
    const int descriptor = ::open(path.c_str(), O_RDONLY | O_NOFOLLOW | O_CLOEXEC);
    if (descriptor < 0)
        Fail(kFilesystemFailure, errno == ELOOP ? "SYMLINK_REFUSED" : "OPEN_FAILED");
    return descriptor;
}

void RequirePrivateDirectory(const std::string& path) {
    const auto slash = path.find_last_of('/');
    const std::string directory = slash == std::string::npos ? "." : path.substr(0, slash);
    struct stat status {};
    if (::stat(directory.c_str(), &status) != 0)
        Fail(kFilesystemFailure, "SECRET_DIRECTORY_MISSING");
    // Group or world access to a share directory defeats the per-party namespace.
    if (status.st_mode & (S_IRWXG | S_IRWXO))
        Fail(kFilesystemFailure, "SECRET_DIRECTORY_NOT_PRIVATE");
    if (status.st_uid != ::getuid())
        Fail(kFilesystemFailure, "SECRET_DIRECTORY_NOT_OWNED");
}

// Create-new + atomic rename. The final name must not already exist: a worker never
// overwrites an immutable artifact.
void WriteBytes(const std::string& path, const std::string& bytes, mode_t mode) {
    struct stat existing {};
    if (::lstat(path.c_str(), &existing) == 0)
        Fail(kFilesystemFailure, "OUTPUT_EXISTS");
    const std::string temporary = path + ".tmp-" + std::to_string(::getpid());
    const int descriptor =
        ::open(temporary.c_str(), O_WRONLY | O_CREAT | O_EXCL | O_NOFOLLOW | O_CLOEXEC, mode);
    if (descriptor < 0)
        Fail(kFilesystemFailure, "CREATE_FAILED");
    std::size_t written = 0;
    while (written < bytes.size()) {
        const ssize_t chunk = ::write(descriptor, bytes.data() + written, bytes.size() - written);
        if (chunk <= 0) {
            ::close(descriptor);
            ::unlink(temporary.c_str());
            Fail(kFilesystemFailure, "WRITE_FAILED");
        }
        written += static_cast<std::size_t>(chunk);
    }
    if (::fsync(descriptor) != 0 || ::close(descriptor) != 0) {
        ::unlink(temporary.c_str());
        Fail(kFilesystemFailure, "FSYNC_FAILED");
    }
    if (::rename(temporary.c_str(), path.c_str()) != 0) {
        ::unlink(temporary.c_str());
        Fail(kFilesystemFailure, "RENAME_FAILED");
    }
}

template <typename T>
std::string SerializeToString(const T& object) {
    std::ostringstream stream;
    try {
        Serial::Serialize(object, stream, SerType::BINARY);
    } catch (const std::exception&) {
        Fail(kSerializationFailure, "SERIALIZE_FAILED");
    }
    return stream.str();
}

template <typename T>
T DeserializeFromString(const std::string& bytes, const char* token) {
    T object;
    std::istringstream stream(bytes);
    try {
        Serial::Deserialize(object, stream, SerType::BINARY);
    } catch (const std::exception&) {
        Fail(kSerializationFailure, token);
    }
    if (!object)
        Fail(kSerializationFailure, token);
    return object;
}

}  // namespace

std::string ReadFileBytes(const std::string& path) {
    const int descriptor = OpenForRead(path);
    struct stat status {};
    if (::fstat(descriptor, &status) != 0) {
        ::close(descriptor);
        Fail(kFilesystemFailure, "STAT_FAILED");
    }
    if (!S_ISREG(status.st_mode)) {
        ::close(descriptor);
        Fail(kFilesystemFailure, "NOT_A_REGULAR_FILE");
    }
    if (static_cast<std::uint64_t>(status.st_size) > kMaxArtifactBytes) {
        ::close(descriptor);
        Fail(kResourceLimit, "ARTIFACT_TOO_LARGE");
    }
    std::string bytes(static_cast<std::size_t>(status.st_size), '\0');
    std::size_t read = 0;
    while (read < bytes.size()) {
        const ssize_t chunk = ::read(descriptor, bytes.data() + read, bytes.size() - read);
        if (chunk <= 0) {
            ::close(descriptor);
            Fail(kFilesystemFailure, "READ_FAILED");
        }
        read += static_cast<std::size_t>(chunk);
    }
    ::close(descriptor);
    return bytes;
}

CryptoContext<DCRTPoly> LoadContext(const std::string& path) {
    // The approved context is always loaded before any other object (blueprint 2.7).
    auto context = DeserializeFromString<CryptoContext<DCRTPoly>>(ReadFileBytes(path),
                                                                 "CONTEXT_DESERIALIZE_FAILED");
    context->Enable(PKE);
    context->Enable(KEYSWITCH);
    context->Enable(LEVELEDSHE);
    context->Enable(ADVANCEDSHE);
    context->Enable(MULTIPARTY);
    VerifyProfile(context);
    return context;
}

void StoreContext(const std::string& path, const CryptoContext<DCRTPoly>& context) {
    WriteBytes(path, SerializeToString(context), 0600);
}

PublicKey<DCRTPoly> LoadPublicKey(const std::string& path) {
    return DeserializeFromString<PublicKey<DCRTPoly>>(ReadFileBytes(path),
                                                      "PUBLIC_KEY_DESERIALIZE_FAILED");
}

void StorePublicKey(const std::string& path, const PublicKey<DCRTPoly>& key) {
    WriteBytes(path, SerializeToString(key), 0600);
}

PrivateKey<DCRTPoly> LoadPrivateKey(const std::string& path) {
    return DeserializeFromString<PrivateKey<DCRTPoly>>(ReadFileBytes(path),
                                                       "PRIVATE_SHARE_DESERIALIZE_FAILED");
}

void StorePrivateShare(const std::string& path, const PrivateKey<DCRTPoly>& key) {
    RequirePrivateDirectory(path);
    WriteBytes(path, SerializeToString(key), 0600);
}

Ciphertext<DCRTPoly> LoadCiphertext(const std::string& path) {
    return DeserializeFromString<Ciphertext<DCRTPoly>>(ReadFileBytes(path),
                                                       "CIPHERTEXT_DESERIALIZE_FAILED");
}

void StoreCiphertext(const std::string& path, const Ciphertext<DCRTPoly>& ciphertext) {
    WriteBytes(path, SerializeToString(ciphertext), 0600);
}

}  // namespace protecmed
