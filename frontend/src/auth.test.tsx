import { render, screen, waitFor, fireEvent } from "@testing-library/react";
import { afterEach, describe, expect, it } from "vitest";
import { AuthProvider, useAuth } from "./auth";
import { installFetch, restoreFetch } from "./test/mockFetch";

afterEach(restoreFetch);

function Consumer() {
  const { user, loading, login, logout } = useAuth();
  if (loading) return <div>loading</div>;
  return (
    <div>
      <span data-testid="user">{user ? user.username : "anon"}</span>
      <button onClick={() => login("Alice", "password123")}>login</button>
      <button onClick={() => logout()}>logout</button>
    </div>
  );
}

describe("AuthProvider", () => {
  it("starts anonymous when /auth/me is 401, then logs in and out", async () => {
    let loggedIn = false;
    installFetch((url, method) => {
      if (url.endsWith("/auth/me")) {
        return loggedIn
          ? { status: 200, data: { id: "1", username: "Alice", is_admin: false, created_at: "" } }
          : { status: 401, data: { detail: "Not authenticated" } };
      }
      if (url.endsWith("/auth/login") && method === "POST") {
        loggedIn = true;
        return { status: 200, data: { id: "1", username: "Alice", is_admin: false, created_at: "" } };
      }
      if (url.endsWith("/auth/logout")) {
        loggedIn = false;
        return { status: 200, data: { detail: "Logged out." } };
      }
      return { status: 404 };
    });

    render(
      <AuthProvider>
        <Consumer />
      </AuthProvider>,
    );

    await waitFor(() => expect(screen.getByTestId("user")).toHaveTextContent("anon"));

    fireEvent.click(screen.getByText("login"));
    await waitFor(() => expect(screen.getByTestId("user")).toHaveTextContent("Alice"));

    fireEvent.click(screen.getByText("logout"));
    await waitFor(() => expect(screen.getByTestId("user")).toHaveTextContent("anon"));
  });
});
