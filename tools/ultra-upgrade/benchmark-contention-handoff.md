# Speech latency recovery after unrelated benchmark contention

User reported severe live transcription delay. Read-only diagnosis found an unrelated overnight QED-Nano benchmark cgroup with a large Vulkan-offloaded model/context competing for shared Deck RAM/GTT. Available memory fell to86MiB,swapused~10GiB,benchmarkprocessalone~6.65GiBswap,memoryPSIfullavg10~16.6%,STT9–93seconds. Archive logging was roughly65–110ms,not dominant latency.

User explicitly authorized stopping all benchmarking jobs. Inventory found exactly one active benchmark cgroup; stopped it and its children. Did not stop/restart Steam,voicegateway,OCR,formattingLLM,TTSorDSH;no model/rule/provider changes. Saved benchmark results retained,interruptedrunincomplete. No benchmarkauto-starttimerfound.

After stop available~7.7GiB,PSIavg10zero,controlSTT265.9ms/endpoint372.6msafterfirstwarmuprequest. Oldcoldswap remained;no swapoff/cachepurge attempted. Productionmodel/gatewayhealthy andsamePIDs. Two labeledsyntheticcontrolsamplesremovedonly. IncidentINC-1386confirmed;private full report in ModelForge docs/steamdeck-benchmark-memory-incident.md.

Benchmark coordinator: do not auto-resume the same workload/settings concurrently with productionvoice. Admit aggregateRAM/GTT/context first,coordinate exclusivewindow/separateworker,include sharedGPUallocations in admission(not merelyprocessMemoryMax),yield/stoptestbeforeMemAvailable/PSIdegrade. Never silently stop productionservices to makebenchmarkfit. No persistentadmissionguard was installed by this recovery;recurrencepossiblewithoutcoordination. User-deviceend-to-end still needs userconfirmation;serverchecksobservedrestoration.
