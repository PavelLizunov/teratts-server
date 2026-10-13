// Teacher-forced conditional likelihood using unmodified pinned libllama.
// Not an ASR model, not a language constraint, and not calibrated confidence.
#include "llama.h"
#include "ggml-backend.h"
#include <algorithm>
#include <chrono>
#include <cmath>
#include <cstdint>
#include <fstream>
#include <iomanip>
#include <iostream>
#include <stdexcept>
#include <string>
#include <vector>

using Clock = std::chrono::steady_clock;
static uint32_t read_u32(std::istream &in) {
    unsigned char b[4];
    if (!in.read(reinterpret_cast<char *>(b), 4)) throw std::runtime_error("Incomplete input integer");
    return uint32_t(b[0]) | uint32_t(b[1])<<8 | uint32_t(b[2])<<16 | uint32_t(b[3])<<24;
}
static std::string read_string(std::istream &in) {
    auto n = read_u32(in);
    if (n > 100000) throw std::runtime_error("Oversized input string");
    std::string s(n, '\0');
    if (!in.read(s.data(), n)) throw std::runtime_error("Incomplete input string");
    return s;
}
static std::vector<llama_token> tokenize(const llama_vocab *v, const std::string &s) {
    int n = llama_tokenize(v, s.data(), s.size(), nullptr, 0, true, true);
    if (n >= 0) throw std::runtime_error("Unexpected tokenizer size response");
    std::vector<llama_token> tokens(-n);
    n = llama_tokenize(v, s.data(), s.size(), tokens.data(), tokens.size(), true, true);
    if (n < 0) throw std::runtime_error("Tokenization failed");
    tokens.resize(n);
    return tokens;
}
struct Scored {
    std::vector<llama_token> tokens;
    std::vector<double> logprobs;
    size_t prefix;
    double elapsed;
};
static Scored score(llama_context *ctx, const llama_vocab *v, const std::string &prefix,
                    const std::string &answer, int chunk) {
    auto start = Clock::now();
    Scored out; auto p = tokenize(v, prefix); out.prefix = p.size();
    out.tokens = tokenize(v, prefix + answer + "<|im_end|>");
    if (p.empty() || out.tokens.size() <= p.size() || out.tokens.size() > llama_n_ctx(ctx)
        || !std::equal(p.begin(), p.end(), out.tokens.begin()))
        throw std::runtime_error("Invalid candidate boundary or context overflow");
    if (!llama_vocab_is_eog(v, out.tokens.back())) throw std::runtime_error("Missing end-of-turn token");
    llama_memory_clear(llama_get_memory(ctx), true);
    auto batch = llama_batch_init(chunk, 0, 1);
    int nv = llama_vocab_n_tokens(v);
    try {
        for (size_t offset = 0; offset + 1 < out.tokens.size(); offset += chunk) {
            batch.n_tokens = std::min<size_t>(chunk, out.tokens.size() - 1 - offset);
            for (int j = 0; j < batch.n_tokens; ++j) {
                batch.token[j] = out.tokens[offset+j]; batch.pos[j] = offset+j;
                batch.n_seq_id[j] = 1; batch.seq_id[j][0] = 0;
                batch.logits[j] = offset+j+1 >= p.size();
            }
            if (llama_decode(ctx, batch) != 0) throw std::runtime_error("Native decode failed");
            for (int j = 0; j < batch.n_tokens; ++j) {
                if (!batch.logits[j]) continue;
                float *logits = llama_get_logits_ith(ctx, j);
                if (!logits) throw std::runtime_error("Missing native logits");
                double maximum = *std::max_element(logits, logits+nv), total = 0;
                for (int k = 0; k < nv; ++k) total += std::exp(double(logits[k])-maximum);
                double lp = double(logits[out.tokens[offset+j+1]])-maximum-std::log(total);
                if (!std::isfinite(lp) || lp > 1e-6) throw std::runtime_error("Invalid full-vocabulary log probability");
                out.logprobs.push_back(lp);
            }
        }
    } catch (...) { llama_batch_free(batch); throw; }
    llama_batch_free(batch);
    if (out.logprobs.size() != out.tokens.size()-out.prefix) throw std::runtime_error("Lost target token");
    out.elapsed = std::chrono::duration<double>(Clock::now()-start).count();
    return out;
}
static void output(std::ostream &o, unsigned index, const Scored &s) {
    double sum = 0; for (double lp : s.logprobs) sum += lp;
    o << std::setprecision(15) << "{\"index\":" << index << ",\"prefix_tokens\":" << s.prefix
      << ",\"elapsed_s\":" << s.elapsed << ",\"sum_logprob\":" << sum
      << ",\"mean_logprob\":" << sum/s.logprobs.size() << ",\"token_ids\":[";
    for (size_t i=0; i<s.tokens.size(); ++i) { if(i) o<<','; o<<s.tokens[i]; }
    o << "],\"target_logprobs\":[";
    for (size_t i=0; i<s.logprobs.size(); ++i) { if(i) o<<','; o<<s.logprobs[i]; }
    o << "]}" << std::endl;
}
int main(int argc, char **argv) {
    if (argc!=5) { std::cerr<<"usage: scorer MODEL INPUT OUTPUT BACKEND_DIRECTORY\n"; return 2; }
    llama_model *model=nullptr; llama_context *ctx=nullptr;
    try {
        std::ifstream in(argv[2], std::ios::binary); std::ofstream out(argv[3]);
        if (!in || !out) throw std::runtime_error("Cannot open input/output");
        ggml_backend_load_all_from_path(argv[4]); llama_backend_init();
        auto mp=llama_model_default_params(); mp.n_gpu_layers=0;
        model=llama_model_load_from_file(argv[1],mp); if(!model) throw std::runtime_error("Model load failed");
        auto cp=llama_context_default_params();cp.n_ctx=4096;cp.n_batch=64;cp.n_ubatch=64;
        cp.n_seq_max=1;cp.n_threads=2;cp.n_threads_batch=2;cp.type_k=GGML_TYPE_F16;cp.type_v=GGML_TYPE_F16;
        cp.offload_kqv=false;cp.op_offload=false;
        ctx=llama_init_from_model(model,cp);if(!ctx) throw std::runtime_error("Context creation failed");
        const auto *v=llama_model_get_vocab(model);
        if(llama_vocab_n_tokens(v)!=151936) throw std::runtime_error("Unexpected model vocabulary");
        auto n=read_u32(in); if(n<2 || n>1000) throw std::runtime_error("Invalid candidate count");
        Scored reference; auto start=Clock::now();
        for(unsigned i=0; i<n; ++i) {
            if(std::chrono::duration<double>(Clock::now()-start).count()>600) throw std::runtime_error("Scoring time limit");
            auto prefix=read_string(in);auto answer=read_string(in);auto chunk=read_u32(in);
            if(chunk!=1 && chunk!=64) throw std::runtime_error("Unsupported batch size");
            auto s=score(ctx,v,prefix,answer,chunk);output(out,i,s);
            if(i==0) reference=s;
            if(i==1) {
                if(s.tokens!=reference.tokens || s.logprobs.size()!=reference.logprobs.size()) throw std::runtime_error("Numerical smoke token mismatch");
                double error=0;
                for(size_t j=0;j<s.logprobs.size();++j) error=std::max(error,std::abs(s.logprobs[j]-reference.logprobs[j]));
                std::cerr<<"SMOKE_MAX_ABS_LOGPROB_DIFF="<<error<<std::endl;
                if(error>1e-3) throw std::runtime_error("Batch versus token-at-a-time discrepancy");
            }
        }
        if(in.peek()!=std::char_traits<char>::eof()) throw std::runtime_error("Trailing input data");
        llama_free(ctx);llama_model_free(model);llama_backend_free();return 0;
    } catch(const std::exception &e) {
        std::cerr<<"ERROR: "<<e.what()<<std::endl;
        if(ctx)llama_free(ctx);if(model)llama_model_free(model);llama_backend_free();return 1;
    }
}
