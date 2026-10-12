import { test, expect } from "@playwright/test";
import { readFileSync } from "node:fs";
import { resolve } from "node:path";

const credentials = JSON.parse(
  readFileSync(resolve("../private-data/browser-test.json"), "utf8"),
);

test("import, review, select source paragraphs and download a persistent draft", async ({
  page,
}) => {
  await page.setViewportSize({ width: 1440, height: 1000 });
  await page.goto("/");
  await page.getByLabel("Email", { exact: true }).fill(credentials.email);
  await page.getByLabel("Password", { exact: true }).fill(credentials.password);
  await page.getByRole("button", { name: "Sign in →" }).click();
  await expect(
    page.getByRole("button", { name: "Resumes", exact: true }),
  ).toBeVisible();
  const response = await page.request.post("/api/v1/jobs", {
    headers: { "X-JobPilot": "1" },
    data: {
      company: "Resume QA",
      title: "Graduate Python Engineer",
      source_url: "https://example.test/resume-browser",
    },
  });
  expect(response.ok()).toBeTruthy();
  const job = await response.json();
  await page.getByRole("button", { name: "Resumes", exact: true }).click();
  await page
    .getByLabel("Read a UTF-8 .txt file")
    .setInputFiles({
      name: "Synthetic resume.txt",
      mimeType: "text/plain",
      buffer: Buffer.from(
        "Synthetic Candidate\nChennai\n\nPython project with SQL.\n\nUnrelated hobby paragraph.",
      ),
    });
  await expect(page.getByLabel("Version name")).toHaveValue("Synthetic resume");
  await page
    .getByRole("button", { name: "Save text version", exact: true })
    .click();
  await page
    .getByLabel("Target opportunity", { exact: true })
    .selectOption(job.id);
  await expect(
    page.getByRole("button", { name: "Create focused draft" }),
  ).toBeDisabled();
  await page
    .getByRole("button", { name: "I reviewed this version’s facts" })
    .click();
  await page
    .getByRole("checkbox", { name: "Unrelated hobby paragraph." })
    .uncheck();
  await page.getByRole("button", { name: "Create focused draft" }).click();
  await expect(page.locator(".resume-preview")).toContainText(
    "Python project with SQL.",
  );
  await expect(page.locator(".resume-preview")).not.toContainText(
    "Unrelated hobby",
  );
  await expect(
    page.getByRole("link", { name: "Download reviewed text" }),
  ).toHaveCount(0);
  await page
    .getByRole("button", { name: "I reviewed this exact draft" })
    .click();
  const waiting = page.waitForEvent("download");
  await page.getByRole("link", { name: "Download reviewed text" }).click();
  const download = await waiting;
  expect(readFileSync((await download.path())!, "utf8")).toBe(
    "Synthetic Candidate\nChennai\n\nPython project with SQL.",
  );
  await page.screenshot({
    path: "../private-data/screenshots/resumes-desktop.png",
    fullPage: true,
  });
  await page.reload();
  await page.getByRole("button", { name: "Resumes", exact: true }).click();
  await page
    .getByRole("button", { name: /Graduate Python Engineer · Reviewed/ })
    .click();
  await expect(
    page.getByRole("link", { name: "Download reviewed text" }),
  ).toBeVisible();
  await page.setViewportSize({ width: 390, height: 844 });
  expect(
    await page.evaluate(
      () => document.documentElement.scrollWidth <= innerWidth,
    ),
  ).toBeTruthy();
  await page.screenshot({
    path: "../private-data/screenshots/resumes-mobile.png",
    fullPage: true,
  });
});
