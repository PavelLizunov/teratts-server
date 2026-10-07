import { cp, mkdir, mkdtemp, rm, symlink } from "node:fs/promises";
import { tmpdir } from "node:os";
import { join } from "node:path";
import { pathToFileURL } from "node:url";

// Explicit override for CI; otherwise use this session's actual profile dependencies.
export const runtime = process.env.DSH_TEST_NODE_MODULES ||
  (process.env.DSH_PROFILE_DIR && join(process.env.DSH_PROFILE_DIR, "node_modules"));
if (!runtime) throw new Error("Set DSH_TEST_NODE_MODULES to the target DSH node_modules directory");
export async function isolatedService(t, overrides = {}) {
  const root = await mkdtemp(join(tmpdir(), "teratts-service-test-"));
  t.after(() => rm(root, { recursive: true, force: true }));
  const scope = join(root, "node_modules", "@deepseek-ai");
  await mkdir(scope, { recursive: true });
  for (const name of ["cordis", "schemastery", "dsh-credentials", "dsh-settings", "dsh-typert-protocol", "dsh-api-remotes"]) {
    await symlink(`${runtime}/@deepseek-ai/${name}`, join(scope, name), "dir");
  }
  const dest = join(root, "node_modules", "dsh-client-ui-teratts");
  await mkdir(dest);
  await cp(new URL("../../lib", import.meta.url), join(dest, "lib"), { recursive: true });
  await cp(new URL("../../package.json", import.meta.url), join(dest, "package.json"));
  const module = await import(pathToFileURL(join(dest, "lib/index.js")));
  const { Context } = await import(`${runtime}/@deepseek-ai/cordis/lib/index.js`);
  const config = {
    endpoint: "http://127.0.0.1:8088", timeoutMs: 1000, maxRetries: 0,
    voice: "ru_f1", language: "ru", stress: false, speechFront: true,
    tokenEnv: "TERATTS_TEST_UNUSED_TOKEN", ...overrides,
  };
  const service = new module.TeraTtsVoiceService(new Context(), () => config);
  t.after(() => service.coordinator.dispose());
  return { service, config, module };
}
