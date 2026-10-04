import assert from "node:assert/strict";
import { readFile } from "node:fs/promises";
import vm from "node:vm";
import test from "node:test";

const source = await readFile(new URL("../lib/client.js", import.meta.url), "utf8");

function renderPlayer() {
  let registration;
  let renderAction;
  let refIndex = 0;
  const owner = Symbol("message");
  const body = {};
  const effects = [];
  const layoutEffects = [];
  const current = { owner, state: "playing", duration: 30, position: 5, rate: 1, complete: true };
  const React = {
    Fragment: "fragment",
    createElement: (type, props, ...children) => ({ type, props: props || {}, children }),
    useState: (initial) => [typeof initial === "function" ? current : initial, () => {}],
    useRef: (initial) => ({ current: refIndex++ === 0 ? owner : initial }),
    useCallback: (callback) => callback,
    useEffect: (effect) => effects.push(effect),
    useLayoutEffect: (effect) => layoutEffects.push(effect),
  };
  const context = vm.createContext({
    window: { __ModuleLoader__: { load(value) { registration = value; } } },
    document: { body }, console, AbortController, setTimeout, clearTimeout, setInterval, clearInterval,
  });
  vm.runInContext(source, context);
  const client = registration.factory((name) => {
    if (name === "react") return React;
    if (name === "react-dom") return { createPortal: (child, target) => ({ type: "portal", child, target }) };
    return {};
  });
  return client.apply({
    remote: { async $mount() {} }, get: () => ({}),
    slots: { inject(_name, register) { return register(); }, register(_descriptor, render) { renderAction = render; return () => {}; } },
  }).then(() => {
    const action = renderAction({ messageId: "message" }).children[1];
    const rendered = action.type(action.props);
    const styles = renderAction({ messageId: "message" }).children[0];
    return { rendered, css: styles.type().children[0], body, effects, layoutEffects, context };
  });
}

test("active speech player escapes the message action row through a body portal", async () => {
  const { rendered, body } = await renderPlayer();
  const portal = rendered.children[1];
  assert.equal(portal.type, "portal");
  assert.equal(portal.target, body);
  assert.equal(portal.child.props["aria-label"], "Speech player");
});

test("player stays centered by default instead of moving to desktop right edge", async () => {
  const { css } = await renderPlayer();
  assert.doesNotMatch(css, /left:auto!important;right:24px/);
  assert.match(css, /left:12px!important;right:12px!important/);
});

test("composer clearance updates and observer/listeners are cleaned up", async () => {
  const { rendered, layoutEffects, context } = await renderPlayer();
  let top = 700;
  let callback;
  let disconnected = false;
  const listeners = new Map();
  const composer = { getBoundingClientRect: () => ({ top, height: 100 }) };
  rendered.children[0].children[0].children[0].props.ref.current = { closest: () => ({ querySelector: () => composer }) };
  const values = new Map();
  rendered.children[1].child.props.ref.current = { style: { setProperty: (name, value) => values.set(name, value) } };
  context.window.innerHeight = 800;
  context.window.addEventListener = (name, fn) => listeners.set(name, fn);
  context.window.removeEventListener = (name, fn) => { assert.equal(listeners.get(name), fn); listeners.delete(name); };
  context.ResizeObserver = class {
    constructor(fn) { callback = fn; }
    observe(element) { assert.equal(element, composer); }
    disconnect() { disconnected = true; }
  };
  const cleanup = layoutEffects[0]();
  assert.equal(values.get("--teratts-composer-offset"), "112px");
  top = 620;
  callback();
  assert.equal(values.get("--teratts-composer-offset"), "192px");
  cleanup();
  assert.equal(disconnected, true);
  assert.equal(listeners.size, 0);
});

test("clicking empty player space cannot bubble into message selection", async () => {
  const { rendered } = await renderPlayer();
  const player = rendered.children[1].child;
  let stopped = false;
  let prevented = false;
  player.props.onClick({ stopPropagation() { stopped = true; }, preventDefault() { prevented = true; } });
  assert.equal(stopped, true);
  assert.equal(prevented, false, "native slider and focus behavior must remain available");
});
