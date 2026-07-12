import { render, screen, fireEvent } from "@testing-library/react";
import { MemoryRouter } from "react-router-dom";
import { describe, expect, it } from "vitest";
import CreatePoll from "./CreatePoll";

function renderPage() {
  return render(
    <MemoryRouter>
      <CreatePoll />
    </MemoryRouter>,
  );
}

describe("CreatePoll wizard", () => {
  it("requires a poll title before advancing", () => {
    renderPage();
    fireEvent.click(screen.getByText("Next: add questions"));
    expect(screen.getByText("Poll needs a title.")).toBeInTheDocument();
  });

  it("enforces 2–10 options per question and lets you review a valid one", () => {
    renderPage();
    fireEvent.change(screen.getByLabelText("Poll title"), { target: { value: "Lunch" } });
    fireEvent.click(screen.getByText("Next: add questions"));

    // Add with a title but no filled options -> options error.
    fireEvent.change(screen.getByLabelText("Title"), { target: { value: "Where?" } });
    fireEvent.click(screen.getByText("Add question"));
    expect(screen.getByText("Each question needs 2–10 options.")).toBeInTheDocument();

    fireEvent.change(screen.getByPlaceholderText("Option 1"), { target: { value: "Tacos" } });
    fireEvent.change(screen.getByPlaceholderText("Option 2"), { target: { value: "Sushi" } });
    fireEvent.click(screen.getByText("Add question"));

    // Question now listed; Review becomes available.
    expect(screen.getByText(/Where\?/)).toBeInTheDocument();
    fireEvent.click(screen.getByText("Review →"));
    expect(screen.getByRole("heading", { name: "Lunch" })).toBeInTheDocument();
  });

  it("renders a script-like option label as inert text (no XSS)", () => {
    renderPage();
    fireEvent.change(screen.getByLabelText("Poll title"), { target: { value: "P" } });
    fireEvent.click(screen.getByText("Next: add questions"));
    fireEvent.change(screen.getByLabelText("Title"), { target: { value: "Q" } });
    const evil = "<script>alert(1)</script>";
    fireEvent.change(screen.getByPlaceholderText("Option 1"), { target: { value: evil } });
    fireEvent.change(screen.getByPlaceholderText("Option 2"), { target: { value: "safe" } });
    fireEvent.click(screen.getByText("Add question"));
    fireEvent.click(screen.getByText("Review →"));

    // The label round-trips as a literal text node (React escaped it); no <script>
    // element was created in the document.
    const item = screen.getByText(evil);
    expect(item).toBeInTheDocument();
    expect(document.querySelector("script")).toBeNull();
  });
});
