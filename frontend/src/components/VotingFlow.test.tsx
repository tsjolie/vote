import { render, screen, waitFor, fireEvent } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";
import VotingFlow from "./VotingFlow";
import { installFetch, restoreFetch } from "../test/mockFetch";

afterEach(restoreFetch);

const VOTE_VIEW = {
  question: { id: "q1", title: "Pick", description: null, is_required: true, option_count: 3 },
  order: [
    { id: "a", label: "Apple", position: 0 },
    { id: "b", label: "Banana", position: 1 },
    { id: "c", label: "Cherry", position: 2 },
  ],
  my_status: "none",
};

const REQUIRED_Q = [
  { id: "q1", position: 0, title: "Pick", description: null, is_required: true, my_status: "none" as const },
];

describe("VotingFlow", () => {
  it("shows progress, submits the permutation, and finishes", async () => {
    const onDone = vi.fn();
    const calls = installFetch((url, method) => {
      if (url.includes("/vote") && method === "GET") return { status: 200, data: VOTE_VIEW };
      if (url.includes("/ballot") && method === "POST") return { status: 200, data: { detail: "ok" } };
      return { status: 404 };
    });

    render(<VotingFlow slug="abc" questions={REQUIRED_Q} startIndex={0} onDone={onDone} />);

    await waitFor(() => expect(screen.getByText("Question 1 of 1")).toBeInTheDocument());
    expect(screen.getByText("Apple")).toBeInTheDocument();

    fireEvent.click(screen.getByText(/Submit & see results/));

    await waitFor(() => expect(onDone).toHaveBeenCalled());
    const ballotCall = calls.find((c) => c.url.includes("/ballot"));
    expect(ballotCall?.body).toEqual({ ranking: ["a", "b", "c"] });
  });

  it("offers Skip on optional questions but not required ones", async () => {
    installFetch(() => ({ status: 200, data: VOTE_VIEW }));

    const { rerender } = render(
      <VotingFlow slug="abc" questions={REQUIRED_Q} startIndex={0} onDone={() => {}} />,
    );
    await waitFor(() => expect(screen.getByText("Apple")).toBeInTheDocument());
    expect(screen.queryByText(/Skip this question/)).toBeNull();

    const optional = [{ ...REQUIRED_Q[0], is_required: false }];
    rerender(<VotingFlow slug="abc" questions={optional} startIndex={0} onDone={() => {}} />);
    await waitFor(() => expect(screen.getByText(/Skip this question/)).toBeInTheDocument());
  });
});
