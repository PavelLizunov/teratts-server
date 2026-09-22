import assert from "node:assert/strict";
import { cp, mkdir, rm, symlink } from "node:fs/promises";
import test from "node:test";
import { fileURLToPath } from "node:url";

const RUNTIME_NODE_MODULES = "/var/lib/dsh/.dsh-releases/v015-rc2-t4x7mz4n/profile/node_modules";

test("runtime @deepseek-ai/dsh-settings exports match DSH 0.1.5-rc.2 (no installSettingsSection/settingsNamespace)", async () => {
  const settingsModule = await import(
    `${RUNTIME_NODE_MODULES}/@deepseek-ai/dsh-settings/lib/index.js`
  );
  assert.equal(
    settingsModule.installSettingsSection,
    undefined,
    "@deepseek-ai/dsh-settings must NOT have installSettingsSection export in 0.1.5-rc.2",
  );
  assert.equal(
    settingsModule.settingsNamespace,
    undefined,
    "@deepseek-ai/dsh-settings must NOT have settingsNamespace export in 0.1.5-rc.2",
  );
  assert.equal(
    typeof settingsModule.default,
    "function",
    "default export must be SettingsProvider class",
  );
});

test("dsh-client-ui-teratts imports cleanly against exact DSH 0.1.5-rc.2 runtime node_modules", async () => {
  const stagingRoot = `/tmp/dsh-plugin-runtime-test-${Date.now()}-${Math.random().toString(36).slice(2, 8)}`;
  const pluginStagingDir = `${stagingRoot}/node_modules/dsh-client-ui-teratts`;

  try {
    await mkdir(`${stagingRoot}/node_modules/@deepseek-ai`, { recursive: true });
    // Symlink @deepseek-ai runtime packages from the real DSH 0.1.5-rc.2 install
    await symlink(
      `${RUNTIME_NODE_MODULES}/@deepseek-ai/cordis`,
      `${stagingRoot}/node_modules/@deepseek-ai/cordis`,
      "dir",
    );
    await symlink(
      `${RUNTIME_NODE_MODULES}/@deepseek-ai/schemastery`,
      `${stagingRoot}/node_modules/@deepseek-ai/schemastery`,
      "dir",
    );
    await symlink(
      `${RUNTIME_NODE_MODULES}/@deepseek-ai/dsh-credentials`,
      `${stagingRoot}/node_modules/@deepseek-ai/dsh-credentials`,
      "dir",
    );
    await symlink(
      `${RUNTIME_NODE_MODULES}/@deepseek-ai/dsh-settings`,
      `${stagingRoot}/node_modules/@deepseek-ai/dsh-settings`,
      "dir",
    );
    await symlink(
      `${RUNTIME_NODE_MODULES}/@deepseek-ai/dsh-typert-protocol`,
      `${stagingRoot}/node_modules/@deepseek-ai/dsh-typert-protocol`,
      "dir",
    );
    await symlink(
      `${RUNTIME_NODE_MODULES}/@deepseek-ai/dsh-api-remotes`,
      `${stagingRoot}/node_modules/@deepseek-ai/dsh-api-remotes`,
      "dir",
    );

    // Copy plugin source to isolated staging directory
    const pluginSourceDir = fileURLToPath(new URL("..", import.meta.url));
    await cp(pluginSourceDir, pluginStagingDir, {
      recursive: true,
      filter: (src) => !src.includes(".git") && !src.includes("test"),
    });

    // Dynamically import the staged plugin using real DSH 0.1.5-rc.2 dependencies
    const pluginModule = await import(`${pluginStagingDir}/lib/index.js`);

    assert.equal(
      typeof pluginModule.apply,
      "function",
      "plugin must export apply function",
    );
    assert.ok(
      Array.isArray(pluginModule.inject),
      "plugin must export inject array",
    );
    assert.equal(
      typeof pluginModule.TeraTtsVoiceService,
      "function",
      "plugin must export TeraTtsVoiceService class",
    );
    assert.equal(
      typeof pluginModule.validateAndResolveEndpoint,
      "function",
      "plugin must export validateAndResolveEndpoint",
    );
    assert.equal(
      typeof pluginModule.validateAndResolvePrepareEndpoint,
      "function",
      "plugin must export validateAndResolvePrepareEndpoint",
    );

    // Test apply(ctx) with real Cordis Context from runtime
    const { Context } = await import(`${stagingRoot}/node_modules/@deepseek-ai/cordis/lib/index.js`);
    const cordisCtx = new Context();

    let installedSection = null;
    let eventHandler = null;

    cordisCtx.inject = (services, callback) => {
      if (services.includes("settings")) {
        callback({
          settings: {
            installSection(owner, ns, schema, entry, hooks) {
              installedSection = { owner, ns, schema, entry, hooks };
            },
          },
        });
      }
    };
    const origOn = cordisCtx.on.bind(cordisCtx);
    cordisCtx.on = (event, handler) => {
      if (event === "session/event") {
        eventHandler = handler;
      }
      return origOn(event, handler);
    };

    pluginModule.apply(cordisCtx, {
      endpoint: "http://127.0.0.1:8088",
      voice: "ru_f1",
      prepareMode: "off",
    });

    assert.ok(installedSection !== null, "installSection must be called via ctx.inject(['settings'])");
    assert.equal(installedSection.ns, "teratts", "settings namespace must be 'teratts'");
    assert.equal(installedSection.entry.prepareMode, "off", "prepareMode must default to 'off'");
    assert.equal(typeof installedSection.hooks.setSource, "function");
    assert.equal(typeof installedSection.hooks.onChange, "function");
    assert.equal(typeof eventHandler, "function", "session/event handler must be registered");
  } finally {
    await rm(stagingRoot, { recursive: true, force: true });
  }
});

test("isolated Cordis composition mounts dsh-client-ui-teratts with SettingsProvider cleanly", async () => {
  const stagingRoot = `/tmp/dsh-plugin-cordis-test-${Date.now()}-${Math.random().toString(36).slice(2, 8)}`;
  const pluginStagingDir = `${stagingRoot}/node_modules/dsh-client-ui-teratts`;

  try {
    await mkdir(`${stagingRoot}/node_modules/@deepseek-ai`, { recursive: true });
    for (const pkg of [
      "cordis",
      "schemastery",
      "dsh-credentials",
      "dsh-settings",
      "dsh-typert-protocol",
      "dsh-api-remotes",
    ]) {
      await symlink(
        `${RUNTIME_NODE_MODULES}/@deepseek-ai/${pkg}`,
        `${stagingRoot}/node_modules/@deepseek-ai/${pkg}`,
        "dir",
      );
    }

    const pluginSourceDir = fileURLToPath(new URL("..", import.meta.url));
    await cp(pluginSourceDir, pluginStagingDir, {
      recursive: true,
      filter: (src) => !src.includes(".git") && !src.includes("test"),
    });

    const { Context } = await import(`${stagingRoot}/node_modules/@deepseek-ai/cordis/lib/index.js`);
    const { default: SettingsProvider } = await import(
      `${stagingRoot}/node_modules/@deepseek-ai/dsh-settings/lib/index.js`
    );
    const pluginModule = await import(`${pluginStagingDir}/lib/index.js`);

    const ctx = new Context();
    // Mount settings service as DSH does on host plane
    new SettingsProvider(ctx, "settings");

    // Mount teratts plugin
    await ctx.plugin(pluginModule, {
      endpoint: "https://teratts.tail9fd337.ts.net",
      voice: "ru_f1",
      prepareMode: "off",
    });

    // Check that settings section "teratts" was registered in SettingsProvider
    const sections = ctx.settings.describe();
    assert.ok(sections.some((s) => s.ns === "teratts"), "settings namespace 'teratts' must be registered");

    // Verify default config
    const registered = sections.find((s) => s.ns === "teratts");
    assert.equal(registered.base.endpoint, "https://teratts.tail9fd337.ts.net");
    assert.equal(registered.base.prepareMode, "off");
    assert.equal(registered.base.voice, "ru_f1");
  } finally {
    await rm(stagingRoot, { recursive: true, force: true });
  }
});

test("lifecycle: mount, unmount (dispose), and remount without duplicate handlers or registration leaks", async () => {
  const stagingRoot = `/tmp/dsh-plugin-lifecycle-test-${Date.now()}-${Math.random().toString(36).slice(2, 8)}`;
  const pluginStagingDir = `${stagingRoot}/node_modules/dsh-client-ui-teratts`;

  try {
    await mkdir(`${stagingRoot}/node_modules/@deepseek-ai`, { recursive: true });
    for (const pkg of [
      "cordis",
      "schemastery",
      "dsh-credentials",
      "dsh-settings",
      "dsh-typert-protocol",
      "dsh-api-remotes",
    ]) {
      await symlink(
        `${RUNTIME_NODE_MODULES}/@deepseek-ai/${pkg}`,
        `${stagingRoot}/node_modules/@deepseek-ai/${pkg}`,
        "dir",
      );
    }

    const pluginSourceDir = fileURLToPath(new URL("..", import.meta.url));
    await cp(pluginSourceDir, pluginStagingDir, {
      recursive: true,
      filter: (src) => !src.includes(".git") && !src.includes("test"),
    });

    const { Context } = await import(`${stagingRoot}/node_modules/@deepseek-ai/cordis/lib/index.js`);
    const { default: SettingsProvider } = await import(
      `${stagingRoot}/node_modules/@deepseek-ai/dsh-settings/lib/index.js`
    );
    const pluginModule = await import(`${pluginStagingDir}/lib/index.js`);

    const ctx = new Context();
    new SettingsProvider(ctx, "settings");

    // 1. First mount
    const fork1 = await ctx.plugin(pluginModule, {
      endpoint: "https://teratts.tail9fd337.ts.net",
      voice: "ru_f1",
      prepareMode: "off",
    });

    assert.equal(ctx.settings.describe().filter((s) => s.ns === "teratts").length, 1);
    assert.ok(ctx.get("terattsVoice") !== undefined, "terattsVoice service must exist on first mount");

    // 2. Unmount (dispose)
    fork1.dispose();

    // 3. Remount
    const fork2 = await ctx.plugin(pluginModule, {
      endpoint: "https://teratts.tail9fd337.ts.net",
      voice: "ru_f1",
      prepareMode: "off",
    });

    assert.equal(
      ctx.settings.describe().filter((s) => s.ns === "teratts").length,
      1,
      "only one teratts section must exist after remount",
    );
    assert.ok(ctx.get("terattsVoice") !== undefined, "terattsVoice service must exist on remount");

    fork2.dispose();
  } finally {
    await rm(stagingRoot, { recursive: true, force: true });
  }
});

test("behavior when settings service is absent: plugin mounts cleanly with base config", async () => {
  const stagingRoot = `/tmp/dsh-plugin-no-settings-test-${Date.now()}-${Math.random().toString(36).slice(2, 8)}`;
  const pluginStagingDir = `${stagingRoot}/node_modules/dsh-client-ui-teratts`;

  try {
    await mkdir(`${stagingRoot}/node_modules/@deepseek-ai`, { recursive: true });
    for (const pkg of [
      "cordis",
      "schemastery",
      "dsh-credentials",
      "dsh-settings",
      "dsh-typert-protocol",
      "dsh-api-remotes",
    ]) {
      await symlink(
        `${RUNTIME_NODE_MODULES}/@deepseek-ai/${pkg}`,
        `${stagingRoot}/node_modules/@deepseek-ai/${pkg}`,
        "dir",
      );
    }

    const pluginSourceDir = fileURLToPath(new URL("..", import.meta.url));
    await cp(pluginSourceDir, pluginStagingDir, {
      recursive: true,
      filter: (src) => !src.includes(".git") && !src.includes("test"),
    });

    const { Context } = await import(`${stagingRoot}/node_modules/@deepseek-ai/cordis/lib/index.js`);
    const pluginModule = await import(`${pluginStagingDir}/lib/index.js`);

    // Context without SettingsProvider
    const ctx = new Context();

    const fork = await ctx.plugin(pluginModule, {
      endpoint: "https://teratts.tail9fd337.ts.net",
      voice: "ru_f1",
      prepareMode: "off",
    });

    assert.ok(ctx.get("terattsVoice") !== undefined, "voice service must mount even without settings");
    const service = ctx.get("terattsVoice");
    assert.equal(service.current().prepareMode, "off");
    assert.equal(service.current().endpoint, "https://teratts.tail9fd337.ts.net");

    fork.dispose();
  } finally {
    await rm(stagingRoot, { recursive: true, force: true });
  }
});

test("effective settings resolution with saved settings.yaml overlay resolves prepareMode to off", async () => {
  const stagingRoot = `/tmp/dsh-plugin-overlay-test-${Date.now()}-${Math.random().toString(36).slice(2, 8)}`;
  const pluginStagingDir = `${stagingRoot}/node_modules/dsh-client-ui-teratts`;

  try {
    await mkdir(`${stagingRoot}/node_modules/@deepseek-ai`, { recursive: true });
    for (const pkg of [
      "cordis",
      "schemastery",
      "dsh-credentials",
      "dsh-settings",
      "dsh-typert-protocol",
      "dsh-api-remotes",
    ]) {
      await symlink(
        `${RUNTIME_NODE_MODULES}/@deepseek-ai/${pkg}`,
        `${stagingRoot}/node_modules/@deepseek-ai/${pkg}`,
        "dir",
      );
    }

    const pluginSourceDir = fileURLToPath(new URL("..", import.meta.url));
    await cp(pluginSourceDir, pluginStagingDir, {
      recursive: true,
      filter: (src) => !src.includes(".git") && !src.includes("test"),
    });

    const { Context } = await import(`${stagingRoot}/node_modules/@deepseek-ai/cordis/lib/index.js`);
    const { default: SettingsProvider } = await import(
      `${stagingRoot}/node_modules/@deepseek-ai/dsh-settings/lib/index.js`
    );
    const pluginModule = await import(`${pluginStagingDir}/lib/index.js`);

    const ctx = new Context();
    const sp = new SettingsProvider(ctx, "settings");
    // Simulate real settings.yaml content
    sp.document = {
      teratts: {
        endpoint: "https://teratts.tail9fd337.ts.net",
        maxRetries: 0,
        timeoutMs: 60000,
      },
    };

    const fork = await ctx.plugin(pluginModule, {
      endpoint: "https://teratts.tail9fd337.ts.net",
      voice: "ru_f1",
      prepareMode: "off",
    });

    const service = ctx.get("terattsVoice");
    const effective = service.current();

    assert.equal(effective.prepareMode, "off", "effective prepareMode must be off");
    assert.equal(effective.maxRetries, 0, "maxRetries must come from overlay");
    assert.equal(effective.endpoint, "https://teratts.tail9fd337.ts.net");

    fork.dispose();
  } finally {
    await rm(stagingRoot, { recursive: true, force: true });
  }
});

test("preparationListener in shadow mode dispatches /prepare asynchronously without blocking audio candidate", async () => {
  const stagingRoot = `/tmp/dsh-plugin-listener-test-${Date.now()}-${Math.random().toString(36).slice(2, 8)}`;
  const pluginStagingDir = `${stagingRoot}/node_modules/dsh-client-ui-teratts`;

  try {
    await mkdir(`${stagingRoot}/node_modules/@deepseek-ai`, { recursive: true });
    for (const pkg of [
      "cordis",
      "schemastery",
      "dsh-credentials",
      "dsh-settings",
      "dsh-typert-protocol",
      "dsh-api-remotes",
    ]) {
      await symlink(
        `${RUNTIME_NODE_MODULES}/@deepseek-ai/${pkg}`,
        `${stagingRoot}/node_modules/@deepseek-ai/${pkg}`,
        "dir",
      );
    }

    const pluginSourceDir = fileURLToPath(new URL("..", import.meta.url));
    await cp(pluginSourceDir, pluginStagingDir, {
      recursive: true,
      filter: (src) => !src.includes(".git") && !src.includes("test"),
    });

    const pluginModule = await import(`${pluginStagingDir}/lib/index.js`);
    const coordinatorModule = await import(`${pluginStagingDir}/lib/coordinator.js`);

    let audioScheduled = false;
    let audioChunkText = "";
    let prepareDispatched = false;
    let finishPrepare;

    const mockService = {
      synthesisRevision: "rev_test",
      preparationRevision: "prep_rev_test",
      preparedTextCache: new coordinatorModule.PreparedTextCache(),
      cache: {
        get: () => undefined,
        set: () => true,
        generation: 1,
      },
      coordinator: {
        isForegroundActive: () => false,
        scheduleSessionCandidate: (_sessionId, cand) => {
          audioScheduled = true;
          audioChunkText = cand.text;
          return true;
        },
      },
      prepareText: async () => {
        prepareDispatched = true;
        return new Promise((resolve) => {
          finishPrepare = () => resolve({
            text: "Серверный подготовленный текст.",
            preparationRevision: "prep_rev_test",
          });
        });
      },
      synthesizeConfigured: async () => ({
        audioBuffer: Buffer.from("wav"),
        mimeType: "audio/wav",
      }),
    };

    const listener = pluginModule.preparationListener(mockService, () => ({
      prepareMode: "shadow",
      endpoint: "https://teratts.tail9fd337.ts.net",
      language: "ru",
      voice: "ru_f1",
    }));

    const mockSession = {
      id: "session_shadow_check",
      deriveMessages: () => [
        {
          id: "msg_turn_1",
          role: "assistant",
          content: [{ type: "text", text: "# Заголовок\n\nПараграф ответа" }],
        },
      ],
    };

    // 1. assistant/message event registers turn
    listener(mockSession, {
      type: "assistant/message",
      data: {
        turn: 1,
        interrupted: false,
        message: {
          id: "msg_turn_1",
          content: [{ type: "text", text: "# Заголовок\n\nПараграф ответа" }],
        },
      },
    });

    // 2. turn/end triggers scheduling
    listener(mockSession, {
      type: "turn/end",
      data: {
        turn: 1,
        reason: { kind: "completed" },
      },
    });

    // Verify invariants:
    // a) Audio candidate was scheduled synchronously with legacy cleanMarkdown text
    assert.equal(audioScheduled, true, "audio candidate must be scheduled immediately");
    assert.equal(audioChunkText, "Заголовок. Параграф ответа", "audio must use legacy clean text in shadow mode");

    // b) /prepare was dispatched asynchronously in background without blocking audio
    assert.equal(prepareDispatched, true, "shadow /prepare must be dispatched in parallel");

    // Complete background prepare
    finishPrepare();
  } finally {
    await rm(stagingRoot, { recursive: true, force: true });
  }
});
