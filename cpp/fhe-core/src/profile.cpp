// Reviewed profile bgv-count-nofn-v2 (blueprint 2.2) and its verification.
// The worker checks the DESERIALIZED context against these compiled values, not
// against a sidecar it was handed.
#include "worker.h"

#include <sstream>

namespace protecmed {

using namespace lbcrypto;

namespace {
constexpr std::uint64_t kPlaintextModulus = 65537;
constexpr std::uint32_t kDigitSize = 10;
}  // namespace

CryptoContext<DCRTPoly> MakeCountContext(std::uint32_t parties) {
    if (parties != 2 && parties != 3)
        Fail(kInvalidCommand, "PARTY_COUNT");
    CCParams<CryptoContextBGVRNS> p;
    p.SetPlaintextModulus(kPlaintextModulus);
    p.SetMultiplicativeDepth(0);
    p.SetThresholdNumOfParties(parties);
    p.SetSecurityLevel(HEStd_128_classic);
    p.SetSecretKeyDist(UNIFORM_TERNARY);
    p.SetMultipartyMode(NOISE_FLOODING_MULTIPARTY);
    p.SetScalingTechnique(FLEXIBLEAUTOEXT);
    p.SetKeySwitchTechnique(BV);
    p.SetDigitSize(kDigitSize);
    p.SetEvalAddCount(5);
    p.SetKeySwitchCount(0);
    CryptoContext<DCRTPoly> context;
    try {
        context = GenCryptoContext(p);
    } catch (const std::exception&) {
        Fail(kCryptoFailure, "CONTEXT_GENERATION_FAILED");
    }
    context->Enable(PKE);
    context->Enable(KEYSWITCH);
    context->Enable(LEVELEDSHE);
    context->Enable(ADVANCEDSHE);
    context->Enable(MULTIPARTY);
    VerifyProfile(context);
    return context;
}

namespace {
std::shared_ptr<CryptoParametersRNS> Parameters(const CryptoContext<DCRTPoly>& context) {
    auto parameters =
        std::dynamic_pointer_cast<CryptoParametersRNS>(context->GetCryptoParameters());
    if (!parameters)
        Fail(kProfileMismatch, "UNEXPECTED_PARAMETER_TYPE");
    return parameters;
}
}  // namespace

void VerifyProfile(const CryptoContext<DCRTPoly>& context) {
    if (!context)
        Fail(kSerializationFailure, "NULL_CONTEXT");
    if (context->getSchemeId() != SCHEME::BGVRNS_SCHEME)
        Fail(kProfileMismatch, "SCHEME_MISMATCH");
    const auto parameters = Parameters(context);
    if (parameters->GetPlaintextModulus() != kPlaintextModulus)
        Fail(kProfileMismatch, "PLAINTEXT_MODULUS_MISMATCH");
    if (parameters->GetStdLevel() != HEStd_128_classic)
        Fail(kProfileMismatch, "SECURITY_LEVEL_MISMATCH");
    if (parameters->GetSecretKeyDist() != UNIFORM_TERNARY)
        Fail(kProfileMismatch, "SECRET_KEY_DIST_MISMATCH");
    if (parameters->GetMultipartyMode() != NOISE_FLOODING_MULTIPARTY)
        Fail(kProfileMismatch, "MULTIPARTY_MODE_MISMATCH");
    if (parameters->GetScalingTechnique() != FLEXIBLEAUTOEXT)
        Fail(kProfileMismatch, "SCALING_TECHNIQUE_MISMATCH");
    if (parameters->GetKeySwitchTechnique() != BV)
        Fail(kProfileMismatch, "KEY_SWITCH_TECHNIQUE_MISMATCH");
    if (parameters->GetDigitSize() != kDigitSize)
        Fail(kProfileMismatch, "DIGIT_SIZE_MISMATCH");
    const auto parties = parameters->GetThresholdNumOfParties();
    if (parties != 2 && parties != 3)
        Fail(kProfileMismatch, "THRESHOLD_PARTY_COUNT_MISMATCH");
    // A forced small ring would be a silent security downgrade, not an optimization.
    if (context->GetRingDimension() < kMinRingDimension)
        Fail(kProfileMismatch, "RING_DIMENSION_TOO_SMALL");
    if (!CryptoContextImpl<DCRTPoly>::GetAllEvalMultKeys().empty() ||
        !CryptoContextImpl<DCRTPoly>::GetAllEvalAutomorphismKeys().empty())
        Fail(kProfileMismatch, "UNEXPECTED_EVALUATION_KEYS");
}

std::uint32_t ContextParties(const CryptoContext<DCRTPoly>& context) {
    return Parameters(context)->GetThresholdNumOfParties();
}

std::string DescribeProfile(const CryptoContext<DCRTPoly>& context) {
    const auto parameters = Parameters(context);
    const auto elements = parameters->GetElementParams();
    std::ostringstream out;
    out << "\"profile_id\": \"bgv-count-nofn-v2\""
        << ", \"openfhe_version\": \"" << GetOPENFHEVersion() << "\""
        << ", \"scheme\": \"BGVRNS\""
        << ", \"ring_dimension\": " << context->GetRingDimension()
        << ", \"plaintext_modulus\": " << parameters->GetPlaintextModulus()
        << ", \"threshold_num_of_parties\": " << parameters->GetThresholdNumOfParties()
        << ", \"security_level\": \"HEStd_128_classic\""
        << ", \"multiparty_mode\": \"NOISE_FLOODING_MULTIPARTY\""
        << ", \"scaling_technique\": \"FLEXIBLEAUTOEXT\""
        << ", \"key_switch_technique\": \"BV\""
        << ", \"digit_size\": " << parameters->GetDigitSize()
        << ", \"tower_count\": " << elements->GetParams().size();
    return out.str();
}

}  // namespace protecmed
