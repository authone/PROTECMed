// PROTECMed v2 — M0 effective-parameter recorder.
// Evidence tool only: it builds the reviewed profile, records every available
// getter, and re-reads the same getters in a SEPARATE process after a binary
// context round trip (blueprint 2.2: "At M0 record every available getter and
// test the checks"; "Some high-level generation settings may not survive
// serialization as independent fields").
// It never generates keys, never touches clinical data and is not part of the
// product. The M2 worker is a different program.
#include "openfhe.h"
#include "cryptocontext-ser.h"
#include "scheme/bgvrns/bgvrns-ser.h"

#include <cstdint>
#include <fstream>
#include <iostream>
#include <memory>
#include <sstream>
#include <stdexcept>
#include <string>
#include <vector>

using namespace lbcrypto;

static CryptoContext<DCRTPoly> MakeCountContext(std::uint32_t n) {
    if (n != 2 && n != 3) throw std::invalid_argument("party count");
    CCParams<CryptoContextBGVRNS> p;
    p.SetPlaintextModulus(65537);
    p.SetMultiplicativeDepth(0);
    p.SetThresholdNumOfParties(n);
    p.SetSecurityLevel(HEStd_128_classic);
    p.SetSecretKeyDist(UNIFORM_TERNARY);
    p.SetMultipartyMode(NOISE_FLOODING_MULTIPARTY);
    p.SetScalingTechnique(FLEXIBLEAUTOEXT);
    p.SetKeySwitchTechnique(BV);
    p.SetDigitSize(10);
    p.SetEvalAddCount(5);
    p.SetKeySwitchCount(0);
    auto cc = GenCryptoContext(p);
    cc->Enable(PKE);
    cc->Enable(KEYSWITCH);
    cc->Enable(LEVELEDSHE);
    cc->Enable(ADVANCEDSHE);
    cc->Enable(MULTIPARTY);
    return cc;
}

template <typename T>
static std::string Str(const T& value) {
    std::ostringstream out;
    out << value;
    return out.str();
}

static std::string Describe(const CryptoContext<DCRTPoly>& cc, const std::string& origin) {
    const auto base = cc->GetCryptoParameters();
    const auto rlwe = std::dynamic_pointer_cast<CryptoParametersRNS>(base);
    if (!rlwe) throw std::runtime_error("unexpected crypto parameter type");
    const auto elementParams = base->GetElementParams();
    const auto& towers = elementParams->GetParams();

    std::ostringstream out;
    out << "{\n";
    out << "  \"origin\": \"" << origin << "\",\n";
    out << "  \"openfhe_version\": \"" << GetOPENFHEVersion() << "\",\n";
    out << "  \"scheme\": \"" << Str(cc->getSchemeId()) << "\",\n";
    out << "  \"ring_dimension\": " << cc->GetRingDimension() << ",\n";
    out << "  \"cyclotomic_order\": " << cc->GetCyclotomicOrder() << ",\n";
    out << "  \"plaintext_modulus\": " << base->GetPlaintextModulus() << ",\n";
    out << "  \"batch_size\": " << base->GetEncodingParams()->GetBatchSize() << ",\n";
    out << "  \"digit_size\": " << base->GetDigitSize() << ",\n";
    out << "  \"threshold_num_of_parties\": " << rlwe->GetThresholdNumOfParties() << ",\n";
    out << "  \"security_level\": \"" << Str(rlwe->GetStdLevel()) << "\",\n";
    out << "  \"secret_key_dist\": \"" << Str(rlwe->GetSecretKeyDist()) << "\",\n";
    out << "  \"multiparty_mode\": \"" << Str(rlwe->GetMultipartyMode()) << "\",\n";
    out << "  \"scaling_technique\": \"" << Str(rlwe->GetScalingTechnique()) << "\",\n";
    out << "  \"key_switch_technique\": \"" << Str(rlwe->GetKeySwitchTechnique()) << "\",\n";
    out << "  \"encryption_technique\": \"" << Str(rlwe->GetEncryptionTechnique()) << "\",\n";
    out << "  \"num_part_q\": " << rlwe->GetNumPartQ() << ",\n";
    out << "  \"tower_count\": " << towers.size() << ",\n";
    out << "  \"ciphertext_modulus_q\": \"" << elementParams->GetModulus() << "\",\n";
    out << "  \"rns_moduli\": [";
    for (std::size_t i = 0; i < towers.size(); ++i)
        out << (i ? ", " : "") << "\"" << towers[i]->GetModulus() << "\"";
    out << "],\n";
    out << "  \"eval_mult_keys_generated\": "
        << (CryptoContextImpl<DCRTPoly>::GetAllEvalMultKeys().empty() ? "false" : "true") << ",\n";
    out << "  \"eval_automorphism_keys_generated\": "
        << (CryptoContextImpl<DCRTPoly>::GetAllEvalAutomorphismKeys().empty() ? "false" : "true")
        << "\n}";
    return out.str();
}

int main(int argc, char** argv) {
    try {
        const std::vector<std::string> args(argv, argv + argc);
        if (args.size() == 4 && args[1] == "gen") {
            const auto n = static_cast<std::uint32_t>(std::stoul(args[2]));
            auto cc = MakeCountContext(n);
            if (!Serial::SerializeToFile(args[3], cc, SerType::BINARY))
                throw std::runtime_error("context serialization failed");
            std::cout << Describe(cc, "generated") << '\n';
            return 0;
        }
        if (args.size() == 3 && args[1] == "inspect") {
            CryptoContext<DCRTPoly> cc;
            if (!Serial::DeserializeFromFile(args[2], cc, SerType::BINARY))
                throw std::runtime_error("context deserialization failed");
            std::cout << Describe(cc, "deserialized") << '\n';
            return 0;
        }
        throw std::invalid_argument("usage: profile_dump gen <2|3> <ctx> | inspect <ctx>");
    } catch (const std::exception& error) {
        std::cerr << "FAIL: " << error.what() << '\n';
        return 1;
    }
}
