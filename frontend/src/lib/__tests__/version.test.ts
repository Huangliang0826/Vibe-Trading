import { expect, it } from "vitest";
import { APP_VERSION } from "../version";

it("prefixes the build version exactly once", () => {
  expect(APP_VERSION).toMatch(/^v\d+\.\d+\.\d+$/);
  expect(APP_VERSION).not.toContain("vv");
});
