import { test, expect } from "@playwright/test";
import { readFileSync } from "node:fs";
import { resolve } from "node:path";

const credentials = JSON.parse(
  readFileSync(resolve("../private-data/browser-test.json"), "utf8"),
);

test("source schedule, regional shortlist, new-role alert and snapshot import", async ({
  page,
}) => {
  test.setTimeout(60000);
  await page.setViewportSize({ width: 1440, height: 1000 });
  await page.goto("/");
  await page.getByLabel("Email", { exact: true }).fill(credentials.email);
  await page.getByLabel("Password", { exact: true }).fill(credentials.password);
  await page.getByRole("button", { name: "Sign in →" }).click();
  await page.getByRole("button", { name: "Discovery", exact: true }).click();
  await page
    .getByRole("button", { name: "+ Add a source", exact: true })
    .click();
  await page
    .getByLabel("Company name", { exact: true })
    .fill("Synthetic QA Company");
  await page.getByLabel("Provider", { exact: true }).selectOption("lever");
  await page.getByLabel("Board name", { exact: true }).fill("qa-company");
  await page.getByRole("button", { name: "Add source", exact: true }).click();
  const source = page.getByRole("article", {
    name: "Synthetic QA Company source",
  });
  await expect(source).toContainText("Last run: succeeded", { timeout: 20000 });
  await page
    .getByRole("button", {
      name: "Software Engineer — Graduate 2027",
      exact: true,
    })
    .click();
  await expect(page.locator(".target-reasons")).toContainText("Chennai");
  await page.getByRole("button", { name: "Needs review", exact: true }).click();
  await page
    .getByRole("button", { name: "Data Analyst — Fresher", exact: true })
    .click();
  await expect(page.locator(".target-reasons")).toContainText(
    "no salary is assumed",
  );
  await source.getByRole("button", { name: "Check now", exact: true }).click();
  const alerts = page.getByRole("region", { name: "New role alerts" });
  await expect(alerts).toContainText("New roles detected", { timeout: 30000 });
  await expect(alerts).toContainText("1 potential matches");
  await alerts.getByRole("button", { name: "Dismiss this update" }).click();
  await expect(alerts).not.toBeVisible();
  await page
    .getByRole("button", { name: "Potential matches", exact: true })
    .click();
  await page
    .getByRole("button", { name: "Data Analyst — Graduate 2027", exact: true })
    .click();
  await page.screenshot({
    path: "../private-data/screenshots/discovery-desktop.png",
    fullPage: true,
  });
  await page
    .getByRole("button", { name: "Add to my opportunities", exact: true })
    .click();
  await expect(
    page.getByRole("heading", { name: "Good things ahead." }),
  ).toBeVisible();
  await expect(page.getByText("lever snapshot", { exact: true })).toBeVisible();
  await page.getByRole("button", { name: "Discovery", exact: true }).click();
  await source.getByRole("button", { name: "Pause", exact: true }).click();
  await expect(source).toContainText("Paused");
  await page.setViewportSize({ width: 390, height: 844 });
  expect(
    await page.evaluate(
      () => document.documentElement.scrollWidth <= window.innerWidth,
    ),
  ).toBeTruthy();
  await page.screenshot({
    path: "../private-data/screenshots/discovery-mobile.png",
    fullPage: true,
  });
});
