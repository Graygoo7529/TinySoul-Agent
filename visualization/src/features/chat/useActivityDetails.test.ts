import { expect, it } from "vitest";
import { workingFromMessages } from "./useActivityDetails";

it("reads installed JSON plan parts without inventing milestone completion", () => {
  const working = workingFromMessages([{ message_index: 2, message: {
    role: "user", label: "plan", parts: [{ type: "json", value: {
      todos: [{ key: "inspect", content: "Read the source", status: "in_progress" }],
      milestones: [{ key: "finding", content: "The dependency is unavailable." }],
    } }],
  } }]);
  expect(working.todos[0]).toMatchObject({ id: "inspect", status: "in_progress" });
  expect(working.milestones[0]).toEqual({ id: "finding", text: "The dependency is unavailable." });
});
