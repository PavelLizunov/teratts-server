import { cp, mkdir, mkdtemp, rm, symlink } from "node:fs/promises";
import { tmpdir } from "node:os";
import { join } from "node:path";
import { pathToFileURL } from "node:url";

// Match the installed runtime used by runtime-import.test.js; never mount live services.
const runtime = "/var/lib/dsh/.dsh-releases/v015-rc2-t4x7mz4n/profile/node_modules";
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
