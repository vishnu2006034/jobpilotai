import { test, expect } from "@playwright/test";
import { readFileSync } from "node:fs";
import { resolve } from "node:path";

const credentials = JSON.parse(
  readFileSync(resolve("../private-data/browser-test.json"), "utf8"),
);

test("profile, opportunity, fit, timeline, reload and sign-out", async ({
  page,
}) => {
  await page.setViewportSize({ width: 1440, height: 1000 });
  await page.goto("/");
  await page.getByLabel("Email", { exact: true }).fill(credentials.email);
  await page.getByLabel("Password", { exact: true }).fill(credentials.password);
  await page.getByRole("button", { name: "Sign in →" }).click();
  await expect(
    page.getByRole("heading", { name: "Good things ahead." }),
  ).toBeVisible();
  await page.getByRole("button", { name: "My profile" }).click();
  await page
    .getByLabel("Full name", { exact: true })
    .fill("Browser QA — synthetic profile");
  await page.getByLabel("Graduation year", { exact: true }).fill("2027");
  await page.getByLabel("Skills", { exact: true }).fill("Python");
  await page.getByLabel("Preferred roles").fill("engineer");
  await page.getByRole("button", { name: "Save profile", exact: true }).click();
  await expect(page.getByRole("status")).toContainText("Profile saved");
  await page
    .getByRole("button", { name: "Opportunities", exact: false })
    .first()
    .click();
  await page
    .getByRole("button", { name: "+ Add opportunity", exact: true })
    .click();
  const dialog = page.getByRole("dialog");
  await dialog
    .getByLabel("Company", { exact: true })
    .fill("Synthetic Example Co");
  await dialog.getByLabel("Role title").fill("Python Engineer — test fixture");
  await dialog.getByLabel("Posting URL").fill("https://example.com/qa-job");
  await dialog.getByLabel("Job location").fill("Bengaluru");
  await dialog.getByLabel("This role supports remote work").check();
  await dialog
    .getByLabel("Description", { exact: true })
    .fill("Synthetic browser-test data. This is not a real vacancy.");
  await dialog.getByLabel("Required skills").fill("Python, SQL");
  await dialog.getByText("Eligibility requirements", { exact: true }).click();
  await dialog.getByLabel("Allowed graduation years").fill("2027");
  await dialog.getByLabel("I checked the posting").check();
  await dialog
    .getByRole("button", { name: "Add opportunity", exact: true })
    .click();
  await expect(dialog).not.toBeVisible();
  await page
    .getByRole("button", {
      name: "Save Python Engineer — test fixture",
      exact: true,
    })
    .click();
  await page.getByRole("button", { name: "Check my fit" }).click();
  const match = page.getByLabel("Match result");
  await expect(match).toContainText("65/100");
  await expect(match).toContainText("eligible");
  await expect(match).toContainText("sql");
  await page.screenshot({
    path: "../private-data/screenshots/opportunities-desktop.png",
    fullPage: true,
  });
  await page.getByRole("button", { name: "Track this application" }).click();
  await expect(page.getByRole("status")).toContainText(
    "No application has been submitted",
  );
  await page.getByLabel("Next status").selectOption("APPLIED");
  await page
    .getByLabel("What happened?")
    .fill("Synthetic confirmation for browser test");
  await page.getByLabel("I confirm this status").check();
  await page.getByRole("button", { name: "Update status" }).click();
  await expect(page.getByRole("status")).toContainText("Status updated");
  await expect(page.locator(".timeline")).toContainText(
    "Synthetic confirmation",
  );
  await page.reload();
  await page
    .getByRole("button", { name: "Applications", exact: false })
    .first()
    .click();
  await page
    .getByRole("button", { name: /Python Engineer — test fixture/ })
    .click();
  await expect(page.locator(".timeline")).toContainText(
    "Synthetic confirmation",
  );
  await page.setViewportSize({ width: 390, height: 844 });
  await expect(
    page.getByRole("heading", { name: "Keep your momentum." }),
  ).toBeVisible();
  expect(
    await page.evaluate(
      () => document.documentElement.scrollWidth <= window.innerWidth,
    ),
  ).toBeTruthy();
  await page.screenshot({
    path: "../private-data/screenshots/applications-mobile.png",
    fullPage: true,
  });
  await page
    .getByRole("button", { name: "Sign out on mobile", exact: true })
    .click();
  await expect(page.getByLabel("Password", { exact: true })).toBeVisible();
});

test("shows backend validation errors inside the add dialog", async ({
  page,
}) => {
  await page.goto("/");
  await page.getByLabel("Email", { exact: true }).fill(credentials.email);
  await page.getByLabel("Password", { exact: true }).fill(credentials.password);
  await page.getByRole("button", { name: "Sign in →" }).click();
  await expect(
    page.getByRole("heading", { name: "Good things ahead." }),
  ).toBeVisible();
  await page.request.post("/api/v1/jobs", {
    headers: { "X-JobPilot": "1" },
    data: {
      company: "Synthetic Example Co",
      title: "Original title",
      source_url: "https://example.com/duplicate-check",
    },
  });
  await page
    .getByRole("button", { name: "+ Add opportunity", exact: true })
    .click();
  const dialog = page.getByRole("dialog");
  await dialog
    .getByLabel("Company", { exact: true })
    .fill("Synthetic Example Co");
  await dialog.getByLabel("Role title").fill("Different details");
  await dialog
    .getByLabel("Posting URL")
    .fill("https://example.com/duplicate-check");
  await dialog
    .getByRole("button", { name: "Add opportunity", exact: true })
    .click();
  await expect(dialog.getByRole("alert")).toContainText("already exists");
  await dialog.getByRole("button", { name: "Cancel", exact: true }).click();
});
