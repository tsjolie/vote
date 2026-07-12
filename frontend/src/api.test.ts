import { afterEach, describe, expect, it } from "vitest";
import { api, ApiError } from "./api";
import { installFetch, restoreFetch } from "./test/mockFetch";

afterEach(restoreFetch);

describe("api client", () => {
  it("adds the CSRF header + JSON content-type on state-changing requests", async () => {
    const calls = installFetch(() => ({ status: 200, data: { ok: true } }));
    await api.post("/polls", { title: "x" });
    expect(calls).toHaveLength(1);
    expect(calls[0].method).toBe("POST");
    expect(calls[0].headers["X-Requested-With"]).toBe("fetch");
    expect(calls[0].headers["Content-Type"]).toBe("application/json");
    expect(calls[0].body).toEqual({ title: "x" });
  });

  it("omits the CSRF header on GET", async () => {
    const calls = installFetch(() => ({ status: 200, data: [] }));
    await api.get("/polls/mine");
    expect(calls[0].headers["X-Requested-With"]).toBeUndefined();
    expect(calls[0].headers["Content-Type"]).toBeUndefined();
  });

  it("throws ApiError carrying the parsed detail on non-2xx", async () => {
    installFetch(() => ({ status: 409, data: { detail: "This question changed, please re-rank." } }));
    await expect(api.post("/x", {})).rejects.toMatchObject({
      name: "ApiError",
      status: 409,
      message: "This question changed, please re-rank.",
    });
  });

  it("surfaces FastAPI validation-array detail messages", async () => {
    installFetch(() => ({
      status: 422,
      data: { detail: [{ msg: "Each question needs 2–10 options." }] },
    }));
    await expect(api.post("/polls", {})).rejects.toMatchObject({
      status: 422,
      message: "Each question needs 2–10 options.",
    });
  });

  it("returns undefined for 204 responses", async () => {
    installFetch(() => ({ status: 204 }));
    await expect(api.del("/x")).resolves.toBeUndefined();
  });

  it("ApiError is an Error subclass", () => {
    const e = new ApiError(403, "nope");
    expect(e).toBeInstanceOf(Error);
    expect(e.status).toBe(403);
  });
});
