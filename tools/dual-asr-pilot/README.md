# Paired isolated ASR pilot — preparation checkpoint

**Not yet a completed model test.** User authorized two candidates: coriollon Whisper Russian Code-Switching and ai-sage GigaAM Multilingual Large CTC. Production Parakeetv3 unchanged. No source transcripts/audio/weights included in this backup.

Pinned fixed manifest:16naturalclips117.4939375seconds (3unknownmarker,6technical,4plainlong,3short),plus1sdigitalsilence and1slownoise;18uniqueSHA. Models get onlyaudio,nooldtranscript/hotwords. CPUworkernewvenv,CUDAhidden,no sharedGPUservicechanges,offlinePrivateNetworkafterdownload,MemoryMax8GiB/CPU2cores/Nice19/RuntimeMax20min. This is recognition-quality pilot,notDeckspeed or goldWER.

WhisperCT2int8_float16artifact@bf64d2a976a268e35041f74233f889f951f0f676 usesfasterwhisper1.2.1CPUint8/beam5/temp0/noVAD/noinitialprompt/nopreviouscondition;standardno-speechfiltersretained. GigaAMLargeCTC@3905cd51c3ed4e88c8edf33f3302969ba480a327,greedyCTC/PyTorch2.10CPUfloat32,inspectionofpinnedcustomcode/hydratargets beforetrust_remote_code,torchweights_only. Runtime0.2.4Vulkannotusedforcandidates.

Preparer selects snapshot from authorizedprivatecorpus;downloader verifiesLFSsize/SHAorGitblob,onlyrequiredfiles;runnervalidates immutable manifest+allmodelSHA,savesatomicprivateperclipoutput,guardsduplicateambiguousdispatch. Failedrunsnotpretendcomplete. PinnedCPUwheelsstagedofflineonlytonewvenv,notproductiondependencyedits. Three tests pass for actual WAVsource/filter/manifest/privateatomicoutput/nohint.

```sh
python3 -m unittest discover -s tools/dual-asr-pilot/tests -v
```

Current preparation:modelsverifiedharness,remoteartifacttransferongoing(resumabletaskownedrsyncafterstoppingslowSCP);runtimeimportsCPUonlyGigaAMcodeOK. No candidateoutputs yet. Full private taskrecord in ModelForge docs/specs/whisper-gigaam-dual-pilot.md. Finishboth18-clipruns,verifycontrols/crossmodelhashpairs and collectprivateevidence beforecompletionclaims. WorkerGPUmemory~14GiBoccupiedbyexistingLLM,isolationnotoptional.
