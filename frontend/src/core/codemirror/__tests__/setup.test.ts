/* Copyright 2024 Marimo. All rights reserved. */

import { EditorState, type Extension } from "@codemirror/state";
import { keymap } from "@codemirror/view";
import { describe, expect, test, vi } from "vitest";
import type { CellId } from "@/core/cells/ids";
import { OverridingHotkeyProvider } from "@/core/hotkeys/hotkeys";
import { Objects } from "@/utils/objects";
import type { CodemirrorCellActions } from "../cells/state";
import { type CodeMirrorSetupOpts, setupCodeMirror } from "../cm";
import { PythonLanguageAdapter } from "../language/languages/python";

vi.mock("@/core/config/config", async (importOriginal) => {
  const original = await importOriginal<{}>();
  return {
    ...original,
    parseAppConfig: () => ({}),
    parseUserConfig: () => ({}),
  };
});
vi.mock("@/core/config/config", async (importOriginal) => {
  const original = await importOriginal<{}>();
  return {
    ...original,
    parseAppConfig: () => ({}),
    parseUserConfig: () => ({}),
  };
});

function namedFunction(name: string) {
  const fn = () => false;
  Object.defineProperty(fn, "name", { value: name });
  return fn;
}

function getOpts() {
  return {
    cellId: "0" as CellId,
    showPlaceholder: false,
    enableAI: false,
    cellActions: {
      toggleHideCode: namedFunction("toggleHideCode"),
      aiCellCompletion: namedFunction("aiCellCompletion"),
      createManyBelow: namedFunction("createManyBelow"),
      onRun: namedFunction("onRun"),
      deleteCell: namedFunction("deleteCell"),
      afterToggleMarkdown: namedFunction("afterToggleMarkdown"),
    } as unknown as CodemirrorCellActions,
    completionConfig: {
      activate_on_typing: false,
      copilot: false,
      codeium_api_key: null,
    },
    keymapConfig: {
      preset: "default",
      overrides: {},
    },
    lspConfig: {
      pylsp: {
        enabled: false,
      },
      diagnostics: {
        enabled: false,
      },
    },
    diagnosticsConfig: {},
    hotkeys: new OverridingHotkeyProvider({}),
    theme: "light",
    displayConfig: { reference_highlighting: false },
  } as const;
}

function setup(config: Partial<CodeMirrorSetupOpts> = {}): Extension[] {
  return setupCodeMirror({ ...getOpts(), ...config });
}

function prettyPrintKeymaps(state: EditorState) {
  const keymaps = state.facet(keymap).flat();
  const prettyKeymaps = keymaps.map((keymap) => {
    const { key, run, any, shift, ...rest } = keymap;
    return {
      key: key?.toString(),
      ...(any ? { any: any.name || "<no name>" } : {}),
      ...(run ? { run: run.name || "<no name>" } : {}),
      ...(shift ? { shift: shift.name || "<no name>" } : {}),
      ...rest,
    };
  });
  return prettyKeymaps;
}

function getDuplicateKeymaps(state: EditorState) {
  const prettyKeymaps = prettyPrintKeymaps(state);
  const groupBy = Objects.groupBy(
    prettyKeymaps,
    (keymap) => keymap.key,
    (keymap) => keymap,
  );
  const duplicates = Objects.fromEntries(
    Object.entries(groupBy).filter(([key, value]) => value.length > 1),
  );
  return duplicates;
}

describe("snapshot all duplicate keymaps", () => {
  // This test just ensures we are not accidentally overlapping keymaps
  // without handling it (precedence or otherwise).

  test("default keymaps", () => {
    const extensions = setup();
    const duplicates = getDuplicateKeymaps(
      EditorState.create({ extensions: extensions }),
    );
    // Total duplicates:
    // if this changes, please make sure to validate they are not conflicting
    expect(Object.values(duplicates).flat().length).toMatchInlineSnapshot("20");
    expect(duplicates).toMatchSnapshot();
  });

  test("vim keymaps", () => {
    const extensions = setup({
      keymapConfig: { preset: "vim", overrides: {} },
    });
    const duplicates = getDuplicateKeymaps(
      EditorState.create({ extensions: extensions }),
    );
    // Total duplicates:
    // if this changes, please make sure to validate they are not conflicting
    expect(Object.values(duplicates).flat().length).toMatchInlineSnapshot("19");
    expect(duplicates).toMatchSnapshot();
  });
});

test("placeholder adds another extension", () => {
  const opts = getOpts();
  const withAI = new PythonLanguageAdapter()
    .getExtension(
      opts.cellId,
      opts.completionConfig,
      opts.hotkeys,
      "marimo-import",
      opts.lspConfig,
    )
    .flat();
  const withoutAI = new PythonLanguageAdapter()
    .getExtension(
      opts.cellId,
      opts.completionConfig,
      opts.hotkeys,
      "none",
      opts.lspConfig,
    )
    .flat();
  expect(withAI.length - 1).toBe(withoutAI.length);
});

test("ai adds more extensions", () => {
  const opts = getOpts();
  const withAI = new PythonLanguageAdapter()
    .getExtension(
      opts.cellId,
      opts.completionConfig,
      opts.hotkeys,
      "ai",
      opts.lspConfig,
    )
    .flat();
  const withoutAI = new PythonLanguageAdapter()
    .getExtension(
      opts.cellId,
      opts.completionConfig,
      opts.hotkeys,
      "none",
      opts.lspConfig,
    )
    .flat();
  expect(withAI.length - 2).toBe(withoutAI.length);
});
