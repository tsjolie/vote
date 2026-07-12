import { render, screen, waitFor, fireEvent } from "@testing-library/react";
import { afterEach, describe, expect, it } from "vitest";
import Results from "./Results";
import { installFetch, restoreFetch } from "../test/mockFetch";

afterEach(restoreFetch);

const PAYLOAD = {
  poll: { id: "p1", slug: "abc", title: "Best fruit", status: "open" },
  is_creator: false,
  questions: [
    {
      question_id: "q1",
      position: 0,
      title: "Pick one",
      description: null,
      options: [
        { id: "a", label: "Apple", position: 0 },
        { id: "b", label: "Banana", position: 1 },
        { id: "c", label: "Cherry", position: 2 },
      ],
      tally: {
        question_id: "q1",
        total_ballots: 9,
        winner_option_id: "a",
        rounds: [
          { round: 1, counts: { a: 4, b: 3, c: 2 }, eliminated: "c", tiebreak_used: "borda" },
          { round: 2, counts: { a: 6, b: 3 }, eliminated: null, tiebreak_used: null },
        ],
      },
    },
  ],
};

describe("Results", () => {
  it("renders the winner, round count, and tiebreak label", async () => {
    installFetch(() => ({ status: 200, data: PAYLOAD }));
    render(<Results slug="abc" />);

    await waitFor(() => expect(screen.getByText("Best fruit")).toBeInTheDocument());
    expect(screen.getByText(/Winner: Apple/)).toBeInTheDocument();
    expect(screen.getByText(/9 counted ballots/)).toBeInTheDocument();

    // Expand the round-by-round breakdown.
    fireEvent.click(screen.getByText(/round-by-round breakdown \(2 rounds\)/));
    expect(screen.getByText("Round 1")).toBeInTheDocument();
    expect(screen.getByText("Round 2")).toBeInTheDocument();
    // Round 1 eliminated Cherry via Borda; round 2 reached majority.
    expect(screen.getByText(/Borda count/)).toBeInTheDocument();
    expect(screen.getByText(/Majority reached/)).toBeInTheDocument();
  });

  it("shows an empty-state when there are no counted ballots", async () => {
    const empty = {
      ...PAYLOAD,
      questions: [
        {
          ...PAYLOAD.questions[0],
          tally: { question_id: "q1", total_ballots: 0, winner_option_id: null, rounds: [] },
        },
      ],
    };
    installFetch(() => ({ status: 200, data: empty }));
    render(<Results slug="abc" />);
    await waitFor(() => expect(screen.getByText(/No counted ballots yet/)).toBeInTheDocument());
  });
});
