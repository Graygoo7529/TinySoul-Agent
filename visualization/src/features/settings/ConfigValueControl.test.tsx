import { renderToStaticMarkup } from "react-dom/server";
import { describe, expect, it } from "vitest";

import { ConfigValueControl } from "./ConfigValueControl";

const onCommit = async () => {};

describe("ConfigValueControl boolean switch", () => {
  it.each([
    [false, "translate-x-0"],
    [true, "translate-x-4"],
  ])("anchors the %s thumb with the expected offset", (value, offset) => {
    const html = renderToStaticMarkup(
      <ConfigValueControl
        value={value}
        disabled={false}
        saving={false}
        onCommit={onCommit}
      />,
    );

    expect(html).toContain("left-0.5");
    expect(html).toContain(offset);
  });
});
