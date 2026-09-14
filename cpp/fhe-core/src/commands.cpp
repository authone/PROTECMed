// The nine worker subcommands of blueprint 5.2.
#include "worker.h"

#include <algorithm>
#include <iostream>
#include <sstream>
#include <string>
#include <vector>

namespace protecmed {

using namespace lbcrypto;

namespace {

const std::string& Require(const std::string& value, const char* token) {
    if (value.empty())
        Fail(kInvalidCommand, token);
    return value;
}

void Reject(const std::string& value, const char* token) {
    if (!value.empty())
        Fail(kInvalidCommand, token);
}

void Emit(const std::string& body) { std::cout << "{" << body << "}\n"; }

// Every ciphertext arriving from outside is checked for context, encoding and shape
// before it is used. An authenticated binary object is not necessarily well formed.
void CheckContext(const CryptoContext<DCRTPoly>& context, const CryptoContext<DCRTPoly>& other,
                  const char* token) {
    if (!other || !(*other == *context))
        Fail(kShapeMismatch, token);
}

void CheckCiphertextShape(const CryptoContext<DCRTPoly>& context,
                          const Ciphertext<DCRTPoly>& ciphertext, std::size_t elements,
                          const char* token) {
    CheckContext(context, ciphertext->GetCryptoContext(), "CIPHERTEXT_CONTEXT_MISMATCH");
    if (ciphertext->GetElements().size() != elements)
        Fail(kShapeMismatch, token);
    if (ciphertext->GetEncodingType() != PACKED_ENCODING)
        Fail(kShapeMismatch, "CIPHERTEXT_ENCODING_MISMATCH");
}

// Load the ordered input counts for add-counts / verify-aggregate under one rule set.
std::vector<Ciphertext<DCRTPoly>> LoadOrderedInputs(const CryptoContext<DCRTPoly>& context,
                                                    const std::vector<std::string>& paths,
                                                    const std::string& expectKeyTag) {
    const auto parties = ContextParties(context);
    if (paths.size() != parties)
        Fail(kShapeMismatch, "INPUT_COUNT_MISMATCH");
    std::vector<Ciphertext<DCRTPoly>> inputs;
    inputs.reserve(paths.size());
    for (const auto& path : paths) {
        auto ciphertext = LoadCiphertext(path);
        // A fresh baseline input has two components; a partial has one.
        CheckCiphertextShape(context, ciphertext, 2, "INPUT_NOT_A_FRESH_CIPHERTEXT");
        if (ciphertext->GetLevel() != 0)
            Fail(kShapeMismatch, "INPUT_LEVEL_MISMATCH");
        if (!expectKeyTag.empty() && ciphertext->GetKeyTag() != expectKeyTag)
            Fail(kShapeMismatch, "INPUT_KEY_TAG_MISMATCH");
        if (!inputs.empty() && ciphertext->GetKeyTag() != inputs.front()->GetKeyTag())
            Fail(kShapeMismatch, "INPUT_KEY_TAG_DISAGREEMENT");
        for (const auto& seen : inputs)
            if (*seen == *ciphertext)
                Fail(kShapeMismatch, "DUPLICATE_INPUT");
        inputs.push_back(ciphertext);
    }
    return inputs;
}

// Deterministic ordered sum, always into a fresh result object. No re-randomization,
// multiplication, rotation, compression or added encrypted zero.
Ciphertext<DCRTPoly> OrderedSum(const CryptoContext<DCRTPoly>& context,
                                const std::vector<Ciphertext<DCRTPoly>>& inputs) {
    try {
        auto aggregate = context->EvalAdd(inputs[0], inputs[1]);
        for (std::size_t i = 2; i < inputs.size(); ++i)
            aggregate = context->EvalAdd(aggregate, inputs[i]);
        if (!aggregate)
            Fail(kCryptoFailure, "EVALADD_FAILED");
        return aggregate;
    } catch (const WorkerError&) {
        throw;
    } catch (const std::exception&) {
        Fail(kCryptoFailure, "EVALADD_FAILED");
    }
}

std::int64_t ReadCountFromStdin() {
    std::string text((std::istreambuf_iterator<char>(std::cin)),
                     std::istreambuf_iterator<char>());
    while (!text.empty() && (text.back() == '\n' || text.back() == '\r' || text.back() == ' '))
        text.pop_back();
    if (text.empty() || text.size() > 5)
        Fail(kRangeFailure, "COUNT_FORMAT");
    if (!std::all_of(text.begin(), text.end(), [](unsigned char c) { return std::isdigit(c); }))
        Fail(kRangeFailure, "COUNT_FORMAT");
    const std::int64_t count = std::stoll(text);
    // 0 <= local_count <= 10000, checked before encryption (blueprint 2.3).
    if (count < 0 || count > kMaxLocalCount)
        Fail(kRangeFailure, "COUNT_OUT_OF_RANGE");
    return count;
}

int ContextCreate(const Arguments& arguments) {
    if (!arguments.haveParties)
        Fail(kInvalidCommand, "MISSING_PARTIES");
    auto context = MakeCountContext(arguments.parties);
    StoreContext(Require(arguments.out, "MISSING_OUT"), context);
    Emit("\"command\": \"context-create\", " + DescribeProfile(context));
    return kOk;
}

int KeygenFirst(const Arguments& arguments) {
    auto context = LoadContext(Require(arguments.context, "MISSING_CONTEXT"));
    auto pair = context->KeyGen();
    if (!pair.good())
        Fail(kCryptoFailure, "KEYGEN_FAILED");
    StorePrivateShare(Require(arguments.secretOut, "MISSING_SECRET_OUT"), pair.secretKey);
    StorePublicKey(Require(arguments.publicOut, "MISSING_PUBLIC_OUT"), pair.publicKey);
    Emit("\"command\": \"keygen-first\", \"round\": 1, \"fresh\": true, \"public_key_tag\": \"" +
         pair.publicKey->GetKeyTag() + "\"");
    return kOk;
}

int KeygenNext(const Arguments& arguments) {
    auto context = LoadContext(Require(arguments.context, "MISSING_CONTEXT"));
    auto incoming = LoadPublicKey(Require(arguments.incoming, "MISSING_INCOMING"));
    CheckContext(context, incoming->GetCryptoContext(), "PUBLIC_KEY_CONTEXT_MISMATCH");
    // Public-key overload with fresh=false: accumulate into the preceding joint key.
    // The private-key-vector debug overload is never used.
    auto pair = context->MultipartyKeyGen(incoming, false, false);
    if (!pair.good())
        Fail(kCryptoFailure, "KEYGEN_FAILED");
    StorePrivateShare(Require(arguments.secretOut, "MISSING_SECRET_OUT"), pair.secretKey);
    StorePublicKey(Require(arguments.publicOut, "MISSING_PUBLIC_OUT"), pair.publicKey);
    Emit("\"command\": \"keygen-next\", \"fresh\": false, \"incoming_key_tag\": \"" +
         incoming->GetKeyTag() + "\", \"public_key_tag\": \"" + pair.publicKey->GetKeyTag() + "\"");
    return kOk;
}

int EncryptCount(const Arguments& arguments) {
    if (!arguments.countStdin)
        Fail(kInvalidCommand, "MISSING_COUNT_STDIN");
    auto context = LoadContext(Require(arguments.context, "MISSING_CONTEXT"));
    auto key = LoadPublicKey(Require(arguments.publicKey, "MISSING_PUBLIC"));
    CheckContext(context, key->GetCryptoContext(), "PUBLIC_KEY_CONTEXT_MISMATCH");
    const std::int64_t count = ReadCountFromStdin();
    Ciphertext<DCRTPoly> ciphertext;
    try {
        auto plaintext = context->MakePackedPlaintext(std::vector<std::int64_t>{count});
        ciphertext = context->Encrypt(key, plaintext);
    } catch (const std::exception&) {
        Fail(kCryptoFailure, "ENCRYPT_FAILED");
    }
    if (!ciphertext)
        Fail(kCryptoFailure, "ENCRYPT_FAILED");
    CheckCiphertextShape(context, ciphertext, 2, "ENCRYPT_SHAPE");
    if (ciphertext->GetKeyTag() != key->GetKeyTag())
        Fail(kShapeMismatch, "ENCRYPT_KEY_TAG");
    StoreCiphertext(Require(arguments.out, "MISSING_OUT"), ciphertext);
    // The local count is never echoed, logged or returned.
    Emit("\"command\": \"encrypt-count\", \"key_tag\": \"" + ciphertext->GetKeyTag() +
         "\", \"elements\": 2");
    return kOk;
}

int AddCounts(const Arguments& arguments) {
    Reject(arguments.secret, "SECRET_NOT_ALLOWED");
    auto context = LoadContext(Require(arguments.context, "MISSING_CONTEXT"));
    auto inputs = LoadOrderedInputs(context, arguments.inputs, arguments.expectKeyTag);
    auto aggregate = OrderedSum(context, inputs);
    StoreCiphertext(Require(arguments.out, "MISSING_OUT"), aggregate);
    Emit("\"command\": \"add-counts\", \"inputs\": " + std::to_string(inputs.size()) +
         ", \"key_tag\": \"" + aggregate->GetKeyTag() + "\"");
    return kOk;
}

int VerifyAggregate(const Arguments& arguments) {
    Reject(arguments.secret, "SECRET_NOT_ALLOWED");
    auto context = LoadContext(Require(arguments.context, "MISSING_CONTEXT"));
    auto inputs = LoadOrderedInputs(context, arguments.inputs, arguments.expectKeyTag);
    auto candidate = LoadCiphertext(Require(arguments.candidate, "MISSING_CANDIDATE"));
    CheckCiphertextShape(context, candidate, 2, "CANDIDATE_NOT_A_FRESH_CIPHERTEXT");
    auto recomputed = OrderedSum(context, inputs);
    // Object comparison: components and their RNS parameters/values, encoding, key tag,
    // level, scale metadata and slot metadata. Nothing is decrypted here.
    const bool equal = (*recomputed == *candidate);
    Emit("\"command\": \"verify-aggregate\", \"equal\": " + std::string(equal ? "true" : "false") +
         ", \"inputs\": " + std::to_string(inputs.size()));
    return equal ? kOk : kAggregateMismatch;
}

int PartialDecrypt(const Arguments& arguments) {
    const auto& role = Require(arguments.role, "MISSING_ROLE");
    if (role != "lead" && role != "main")
        Fail(kRoleFailure, "INVALID_ROLE");
    auto context = LoadContext(Require(arguments.context, "MISSING_CONTEXT"));
    auto share = LoadPrivateKey(Require(arguments.secret, "MISSING_SECRET"));
    CheckContext(context, share->GetCryptoContext(), "SHARE_CONTEXT_MISMATCH");
    auto ciphertext = LoadCiphertext(Require(arguments.ciphertext, "MISSING_CIPHERTEXT"));
    CheckCiphertextShape(context, ciphertext, 2, "AGGREGATE_NOT_A_FRESH_CIPHERTEXT");
    std::vector<Ciphertext<DCRTPoly>> partial;
    try {
        partial = role == "lead" ? context->MultipartyDecryptLead({ciphertext}, share)
                                 : context->MultipartyDecryptMain({ciphertext}, share);
    } catch (const std::exception&) {
        Fail(kCryptoFailure, "PARTIAL_DECRYPT_FAILED");
    }
    if (partial.size() != 1 || !partial[0])
        Fail(kShapeMismatch, "PARTIAL_SHAPE");
    StoreCiphertext(Require(arguments.out, "MISSING_OUT"), partial[0]);
    Emit("\"command\": \"partial-decrypt\", \"role\": \"" + role + "\", \"elements\": " +
         std::to_string(partial[0]->GetElements().size()));
    return kOk;
}

int Fuse(const Arguments& arguments) {
    Reject(arguments.secret, "SECRET_NOT_ALLOWED");
    if (!arguments.haveParties)
        Fail(kInvalidCommand, "MISSING_PARTIES");
    auto context = LoadContext(Require(arguments.context, "MISSING_CONTEXT"));
    const auto parties = ContextParties(context);
    if (arguments.parties != parties)
        Fail(kProfileMismatch, "PARTY_COUNT_MISMATCH");
    // The application gate runs before this program is invoked. This count check is a
    // shape check, not evidence that the roster approved anything.
    if (arguments.inputs.size() != parties)
        Fail(kRoleFailure, "PARTIAL_COUNT_MISMATCH");
    std::vector<Ciphertext<DCRTPoly>> partials;
    for (const auto& path : arguments.inputs) {
        auto partial = LoadCiphertext(path);
        CheckCiphertextShape(context, partial, 1, "PARTIAL_SHAPE");
        for (const auto& seen : partials)
            if (*seen == *partial)
                Fail(kRoleFailure, "DUPLICATE_PARTIAL");
        partials.push_back(partial);
    }
    Plaintext plaintext;
    DecryptResult status;
    try {
        status = context->MultipartyDecryptFusion(partials, &plaintext);
    } catch (const std::exception&) {
        Fail(kCryptoFailure, "FUSION_FAILED");
    }
    // isValid is a decoding check, not evidence that the roster participated.
    if (!status.isValid || !plaintext)
        Fail(kCryptoFailure, "FUSION_FAILED");
    plaintext->SetLength(1);
    const auto values = plaintext->GetPackedValue();
    if (values.size() != 1)
        Fail(kShapeMismatch, "PLAINTEXT_SHAPE");
    const std::int64_t aggregate = values[0];
    if (aggregate < 0 || aggregate > static_cast<std::int64_t>(parties) * kMaxLocalCount)
        Fail(kRangeFailure, "AGGREGATE_OUT_OF_RANGE");
    Emit("\"command\": \"fuse\", \"parties\": " + std::to_string(parties) +
         ", \"aggregate\": " + std::to_string(aggregate));
    return kOk;
}

int InspectPublic(const Arguments& arguments) {
    const auto& type = Require(arguments.type, "MISSING_TYPE");
    const auto& artifact = Require(arguments.artifact, "MISSING_ARTIFACT");
    if (type == "context") {
        auto context = LoadContext(artifact);
        Emit("\"command\": \"inspect-public\", \"type\": \"context\", " +
             DescribeProfile(context));
        return kOk;
    }
    auto context = LoadContext(Require(arguments.context, "MISSING_CONTEXT"));
    if (type == "public-key") {
        auto key = LoadPublicKey(artifact);
        CheckContext(context, key->GetCryptoContext(), "PUBLIC_KEY_CONTEXT_MISMATCH");
        Emit("\"command\": \"inspect-public\", \"type\": \"public-key\", \"key_tag\": \"" +
             key->GetKeyTag() + "\", \"elements\": " +
             std::to_string(key->GetPublicElements().size()) + ", \"ring_dimension\": " +
             std::to_string(context->GetRingDimension()));
        return kOk;
    }
    if (type == "ciphertext" || type == "partial") {
        auto ciphertext = LoadCiphertext(artifact);
        CheckContext(context, ciphertext->GetCryptoContext(), "CIPHERTEXT_CONTEXT_MISMATCH");
        const auto elements = ciphertext->GetElements().size();
        if (type == "ciphertext" && elements != 2)
            Fail(kShapeMismatch, "NOT_A_FRESH_CIPHERTEXT");
        if (type == "partial" && elements != 1)
            Fail(kShapeMismatch, "NOT_A_PARTIAL");
        // Sanitized description only. Nothing here decrypts or reveals a payload.
        Emit("\"command\": \"inspect-public\", \"type\": \"" + type + "\", \"key_tag\": \"" +
             ciphertext->GetKeyTag() + "\", \"elements\": " + std::to_string(elements) +
             ", \"level\": " + std::to_string(ciphertext->GetLevel()) + ", \"slots\": " +
             std::to_string(ciphertext->GetSlots()) + ", \"noise_scale_degree\": " +
             std::to_string(ciphertext->GetNoiseScaleDeg()) + ", \"ring_dimension\": " +
             std::to_string(context->GetRingDimension()));
        return kOk;
    }
    Fail(kInvalidCommand, "UNKNOWN_ARTIFACT_TYPE");
}

}  // namespace

int Dispatch(const Arguments& arguments) {
    if (arguments.command == "context-create") return ContextCreate(arguments);
    if (arguments.command == "keygen-first") return KeygenFirst(arguments);
    if (arguments.command == "keygen-next") return KeygenNext(arguments);
    if (arguments.command == "encrypt-count") return EncryptCount(arguments);
    if (arguments.command == "add-counts") return AddCounts(arguments);
    if (arguments.command == "verify-aggregate") return VerifyAggregate(arguments);
    if (arguments.command == "partial-decrypt") return PartialDecrypt(arguments);
    if (arguments.command == "fuse") return Fuse(arguments);
    if (arguments.command == "inspect-public") return InspectPublic(arguments);
    Fail(kInvalidCommand, "UNKNOWN_COMMAND");
}

}  // namespace protecmed
