// sidrender: play one sub-song of a SID file with libsidplayfp and write the sound to stdout as raw mono int16 at
// 48 kHz, much faster than real time - for tools/find_lengths.py (the repeat search needs the sound).
//
//   sidrender <file.sid> <song (1-based, 0 = start song)> <seconds> [kernal basic chargen]
//
// The ROMs are needed by RSID tunes only (VICE has them). On stderr: "songs <n> start <n> chips <n>" first.
// Build: c++ -O2 -std=c++17 sidrender.cpp -I$(brew --prefix libsidplayfp)/include \
//        -L$(brew --prefix libsidplayfp)/lib -lsidplayfp -o sidrender
#include <sidplayfp/sidplayfp.h>
#include <sidplayfp/SidTune.h>
#include <sidplayfp/SidTuneInfo.h>
#include <sidplayfp/SidConfig.h>
#include <sidplayfp/builders/sidlite.h>

#include <cstdio>
#include <cstdlib>
#include <fstream>
#include <iterator>
#include <vector>

static std::vector<uint8_t> rom(const char *path, size_t size)
{
    std::ifstream f(path, std::ios::binary);
    std::vector<uint8_t> d((std::istreambuf_iterator<char>(f)), std::istreambuf_iterator<char>());
    if (d.size() != size)
        d.clear();
    return d;
}

int main(int argc, char **argv)
{
    if (argc < 4) {
        std::fprintf(stderr, "usage: sidrender file.sid song seconds [kernal basic chargen]\n");
        return 2;
    }
    SidTune tune(argv[1]);
    if (!tune.getStatus()) {
        std::fprintf(stderr, "error %s\n", tune.statusString());
        return 1;
    }
    const unsigned int song = tune.selectSong(std::atoi(argv[2]));
    const double seconds = std::atof(argv[3]);
    const SidTuneInfo *ti = tune.getInfo();
    std::fprintf(stderr, "songs %u start %u chips %d song %u\n", ti->songs(), ti->startSong(), ti->sidChips(), song);

    sidplayfp engine;
    std::vector<uint8_t> k, b, c;
    if (argc >= 7) {
        k = rom(argv[4], 8192);
        b = rom(argv[5], 8192);
        c = rom(argv[6], 4096);
        engine.setRoms(k.empty() ? nullptr : k.data(), b.empty() ? nullptr : b.data(), c.empty() ? nullptr : c.data());
    }
    SIDLiteBuilder sids("sidrender");
    SidConfig cfg;
    cfg.frequency = 48000;
    cfg.sidEmulation = &sids;
    cfg.samplingMethod = SidConfig::INTERPOLATE;
    if (!engine.config(cfg)) {
        std::fprintf(stderr, "error %s\n", engine.error());
        return 1;
    }
    if (!engine.load(&tune)) {
        std::fprintf(stderr, "error %s\n", engine.error());
        return 1;
    }
    engine.initMixer(false);
    std::vector<short> buf(1 << 16);
    const unsigned int cycles = 20000;
    while (engine.timeMs() < seconds * 1000.0) {
        const int n = engine.play(cycles);
        if (n < 0) {
            std::fprintf(stderr, "error %s\n", engine.error());
            return 1;
        }
        if (n == 0)
            continue;
        if (static_cast<size_t>(n) > buf.size())
            buf.resize(n);
        const unsigned int m = engine.mix(buf.data(), n);
        if (std::fwrite(buf.data(), sizeof(short), m, stdout) != m)
            return 0;                       // the reader has seen enough
    }
    return 0;
}
