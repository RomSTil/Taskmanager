import { cleanup, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";
import type { TaskmanApi } from "./api";
import IntegrationsView from "./IntegrationsView";

afterEach(cleanup);

function apiStub() {
  return {
    listMarketAccounts: vi.fn().mockResolvedValue([]),
    listMarketOrders: vi.fn().mockResolvedValue([]),
    listDirectAccounts: vi.fn().mockResolvedValue([]),
    listOzonAccounts: vi.fn().mockResolvedValue([]),
    listMaxBots: vi.fn().mockResolvedValue([]),
    listMaxAccessRequests: vi.fn().mockResolvedValue([]),
    createMarketAccount: vi.fn().mockResolvedValue({ id: "market-1" }),
    createMaxBot: vi.fn().mockResolvedValue({
      id: "bot-1",
      name: "Сборка",
      integration: "market",
      webhook_secret: "once-secret",
    }),
    registerMaxWebhook: vi.fn().mockResolvedValue({ ok: true }),
    createOzonAccount: vi.fn().mockResolvedValue({ id: "ozon-1", name: "Основной Ozon" }),
  } as unknown as TaskmanApi;
}

describe("IntegrationsView", () => {
  it("adds a Yandex Market account from the UI", async () => {
    const api = apiStub();
    render(<IntegrationsView api={api} />);

    await screen.findByText("Магазин ещё не подключён. Заполни форму выше.");
    fireEvent.change(screen.getByLabelText("Название магазина"), { target: { value: "Основной магазин" } });
    fireEvent.change(screen.getByLabelText("Campaign ID"), { target: { value: "149086260" } });
    fireEvent.change(screen.getByLabelText("API-Key Яндекс Маркета"), { target: { value: "market-api-key-with-enough-length" } });
    fireEvent.click(screen.getByRole("button", { name: "Подключить магазин" }));

    await waitFor(() => expect(api.createMarketAccount).toHaveBeenCalledWith({
      name: "Основной магазин",
      campaign_id: 149086260,
      api_key: "market-api-key-with-enough-length",
      poll_interval_seconds: 60,
    }));
    expect(await screen.findByText(/Магазин подключён/)).toBeInTheDocument();
  });

  it("creates a MAX bot for the Market integration", async () => {
    const api = apiStub();
    render(<IntegrationsView api={api} />);

    await screen.findByText("Бот для заказов ещё не подключён.");
    fireEvent.change(screen.getByLabelText("Название бота"), { target: { value: "Сборка" } });
    fireEvent.change(screen.getByLabelText("Bot token MAX"), { target: { value: "max-bot-token-with-enough-length" } });
    fireEvent.click(screen.getByRole("button", { name: "Подключить MAX" }));

    await waitFor(() => expect(api.createMaxBot).toHaveBeenCalledWith({
      name: "Сборка",
      token: "max-bot-token-with-enough-length",
      integration: "market",
      allowlist: [],
    }));
    expect(api.registerMaxWebhook).toHaveBeenCalledWith("bot-1");
    expect(await screen.findByText("once-secret")).toBeInTheDocument();
  });

  it("adds an Ozon Seller account from the UI", async () => {
    const api = apiStub();
    render(<IntegrationsView api={api} />);

    await screen.findByText("Ozon Seller ещё не подключён.");
    fireEvent.change(screen.getByLabelText("Название кабинета"), { target: { value: "Основной Ozon" } });
    fireEvent.change(screen.getByLabelText("Client-Id"), { target: { value: "123456" } });
    fireEvent.change(screen.getByLabelText("Api-Key"), { target: { value: "ozon-api-key-value" } });
    fireEvent.click(screen.getByRole("button", { name: "Подключить Ozon" }));

    await waitFor(() => expect(api.createOzonAccount).toHaveBeenCalledWith({
      name: "Основной Ozon",
      client_id: "123456",
      api_key: "ozon-api-key-value",
      poll_interval_minutes: 1,
    }));
  });
});
