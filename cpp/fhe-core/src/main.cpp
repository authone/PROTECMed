// Strict argv parsing and dispatch for the PROTECMed worker.
//
// One short-lived process per operation and one epoch per process: this program never
// loops over runs and never caches state between invocations, so OpenFHE's global
// context and key caches are not manipulated concurrently (blueprint 2.7).
// The service invokes it as an argv array with shell=false, a fixed binary path, a
// timeout and a minimal environment. Counts and secret bytes never appear in argv.
#include "worker.h"

#include <iostream>
#include <map>
#include <set>
#include <string>
#include <vector>

namespace protecmed {

[[noreturn]] void Fail(ExitCode code, const std::string& token) {
    throw WorkerError(code, token);
}

namespace {

const std::map<std::string, std::set<std::string>>& AllowedFlags() {
    static const std::map<std::string, std::set<std::string>> allowed = {
        {"context-create", {"--parties", "--out"}},
        {"keygen-first", {"--context", "--secret-out", "--public-out"}},
        {"keygen-next", {"--context", "--incoming", "--secret-out", "--public-out"}},
        {"encrypt-count", {"--context", "--public", "--count-stdin", "--out"}},
        {"add-counts", {"--context", "--input", "--out", "--expect-key-tag"}},
        {"verify-aggregate", {"--context", "--input", "--candidate", "--expect-key-tag"}},
        {"partial-decrypt", {"--context", "--secret", "--ciphertext", "--role", "--out"}},
        {"fuse", {"--context", "--parties", "--partial"}},
        {"inspect-public", {"--context", "--artifact", "--type"}},
    };
    return allowed;
}

void AssignOnce(std::string& field, const std::string& value, const std::string& flag) {
    if (!field.empty())
        Fail(kInvalidCommand, "REPEATED_FLAG");
    if (value.empty())
        Fail(kInvalidCommand, "EMPTY_FLAG_VALUE");
    field = value;
    (void)flag;
}

Arguments Parse(const std::vector<std::string>& argv) {
    if (argv.size() < 2)
        Fail(kInvalidCommand, "MISSING_COMMAND");
    Arguments arguments;
    arguments.command = argv[1];
    const auto entry = AllowedFlags().find(arguments.command);
    if (entry == AllowedFlags().end())
        Fail(kInvalidCommand, "UNKNOWN_COMMAND");
    const auto& allowed = entry->second;

    for (std::size_t i = 2; i < argv.size(); ++i) {
        const std::string& flag = argv[i];
        if (flag.rfind("--", 0) != 0)
            Fail(kInvalidCommand, "UNEXPECTED_POSITIONAL_ARGUMENT");
        if (!allowed.count(flag))
            Fail(kInvalidCommand, "FLAG_NOT_ALLOWED_FOR_COMMAND");
        if (flag == "--count-stdin") {
            if (arguments.countStdin)
                Fail(kInvalidCommand, "REPEATED_FLAG");
            arguments.countStdin = true;
            continue;
        }
        if (i + 1 >= argv.size())
            Fail(kInvalidCommand, "MISSING_FLAG_VALUE");
        const std::string& value = argv[++i];
        if (value.rfind("--", 0) == 0)
            Fail(kInvalidCommand, "MISSING_FLAG_VALUE");
        if (flag == "--input" || flag == "--partial") {
            if (arguments.inputs.size() >= 3)
                Fail(kInvalidCommand, "TOO_MANY_INPUTS");
            arguments.inputFlag = flag;
            arguments.inputs.push_back(value);
        } else if (flag == "--parties") {
            if (arguments.haveParties)
                Fail(kInvalidCommand, "REPEATED_FLAG");
            if (value != "2" && value != "3")
                Fail(kInvalidCommand, "PARTY_COUNT");
            arguments.parties = static_cast<std::uint32_t>(value[0] - '0');
            arguments.haveParties = true;
        } else if (flag == "--context") {
            AssignOnce(arguments.context, value, flag);
        } else if (flag == "--incoming") {
            AssignOnce(arguments.incoming, value, flag);
        } else if (flag == "--public") {
            AssignOnce(arguments.publicKey, value, flag);
        } else if (flag == "--secret") {
            AssignOnce(arguments.secret, value, flag);
        } else if (flag == "--secret-out") {
            AssignOnce(arguments.secretOut, value, flag);
        } else if (flag == "--public-out") {
            AssignOnce(arguments.publicOut, value, flag);
        } else if (flag == "--ciphertext") {
            AssignOnce(arguments.ciphertext, value, flag);
        } else if (flag == "--candidate") {
            AssignOnce(arguments.candidate, value, flag);
        } else if (flag == "--out") {
            AssignOnce(arguments.out, value, flag);
        } else if (flag == "--role") {
            AssignOnce(arguments.role, value, flag);
        } else if (flag == "--artifact") {
            AssignOnce(arguments.artifact, value, flag);
        } else if (flag == "--type") {
            AssignOnce(arguments.type, value, flag);
        } else if (flag == "--expect-key-tag") {
            AssignOnce(arguments.expectKeyTag, value, flag);
        } else {
            Fail(kInvalidCommand, "UNKNOWN_FLAG");
        }
    }
    if (!arguments.inputs.empty()) {
        const bool wantsPartial = arguments.command == "fuse";
        if (wantsPartial != (arguments.inputFlag == "--partial"))
            Fail(kInvalidCommand, "WRONG_INPUT_FLAG");
    }
    return arguments;
}

}  // namespace
}  // namespace protecmed

int main(int argc, char** argv) {
    const std::vector<std::string> arguments(argv, argv + argc);
    try {
        return protecmed::Dispatch(protecmed::Parse(arguments));
    } catch (const protecmed::WorkerError& error) {
        // Sanitized symbolic token only; never an OpenFHE message or a filesystem path.
        std::cerr << error.what() << '\n';
        return error.code();
    } catch (const std::exception&) {
        std::cerr << "UNEXPECTED_FAILURE\n";
        return protecmed::kCryptoFailure;
    }
}
