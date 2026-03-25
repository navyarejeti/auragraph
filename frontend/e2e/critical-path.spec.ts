/**
 * e2e/critical-path.spec.ts
 *
 * Critical-path E2E tests for AuraGraph.
 * All backend API calls are intercepted with Playwright's route mock so the
 * tests run without a live server.
 */

import { test, expect, Page } from '@playwright/test';

const API = 'http://localhost:8000';

// ─── Shared mock helpers ──────────────────────────────────────────────────────

/** Wire up baseline API mocks that almost every test needs. */
async function mockBaseAPI(page: Page) {
  // Demo login
  await page.route(`${API}/auth/demo-login`, (route) =>
    route.fulfill({
      status: 200,
      contentType: 'application/json',
      body: JSON.stringify({
        access_token: 'demo-token',
        token_type: 'bearer',
        user_id: 'demo-user',
        name: 'Demo Student',
        demo_notebook_id: null,
      }),
    })
  );

  // Register
  await page.route(`${API}/auth/register`, (route) =>
    route.fulfill({
      status: 200,
      contentType: 'application/json',
      body: JSON.stringify({
        access_token: 'test-token',
        token_type: 'bearer',
        user_id: 'test-user-1',
        name: 'Test User',
      }),
    })
  );

  // Login
  await page.route(`${API}/auth/login`, (route) =>
    route.fulfill({
      status: 200,
      contentType: 'application/json',
      body: JSON.stringify({
        access_token: 'test-token',
        token_type: 'bearer',
        user_id: 'test-user-1',
        name: 'Test User',
      }),
    })
  );

  // Notebook list (paginated)
  await page.route(`${API}/api/notebooks*`, (route) => {
    if (route.request().method() === 'GET') {
      return route.fulfill({
        status: 200,
        contentType: 'application/json',
        body: JSON.stringify({
          total: 1,
          offset: 0,
          limit: 50,
          notebooks: [
            {
              id: 'nb-001',
              name: 'Digital Signal Processing',
              course: 'EC301 — DSP',
              created_at: new Date().toISOString(),
              sections: [],
              mastery_score: 0,
            },
          ],
        }),
      });
    }
    // POST create notebook
    return route.fulfill({
      status: 200,
      contentType: 'application/json',
      body: JSON.stringify({
        id: 'nb-new',
        name: 'New Notebook',
        course: 'TEST101',
        created_at: new Date().toISOString(),
        sections: [],
        mastery_score: 0,
      }),
    });
  });

  // Graph / usage endpoints — avoid network errors
  await page.route(`${API}/api/graph*`, (route) =>
    route.fulfill({ status: 200, contentType: 'application/json', body: JSON.stringify({ nodes: [], edges: [] }) })
  );
  await page.route(`${API}/api/usage`, (route) =>
    route.fulfill({ status: 200, contentType: 'application/json', body: JSON.stringify({ hourly: 0, daily: 0 }) })
  );
}

// ─── Test 1: Demo login lands on dashboard ────────────────────────────────────

test('demo login navigates to dashboard', async ({ page }) => {
  await mockBaseAPI(page);

  await page.goto('/');
  // Should land on login page
  await expect(page.getByText(/Sign in to AuraGraph|AuraGraph/i).first()).toBeVisible();

  // Click the demo button
  const demoBtn = page.getByRole('button', { name: /Try Demo/i });
  await expect(demoBtn).toBeVisible();
  await demoBtn.click();

  // Should navigate to dashboard
  await page.waitForURL('**/dashboard', { timeout: 10_000 });
  await expect(page).toHaveURL(/dashboard/);

  // Dashboard should show the "New Notebook" button
  await expect(page.getByRole('button', { name: /New Notebook/i })).toBeVisible();
});

// ─── Test 2: Create notebook modal validation ─────────────────────────────────

test('create notebook modal validates and submits', async ({ page }) => {
  await mockBaseAPI(page);

  // Navigate directly to dashboard with a mocked auth token
  await page.goto('/');
  await page.getByRole('button', { name: /Try Demo/i }).click();
  await page.waitForURL('**/dashboard', { timeout: 10_000 });

  // Open create notebook modal
  await page.getByRole('button', { name: /New Notebook/i }).first().click();

  // Modal should be visible
  await expect(page.getByRole('heading', { name: /New Notebook/i })).toBeVisible();

  // Try submitting empty form — should show validation errors
  await page.getByRole('button', { name: /Create Notebook/i }).click();
  await expect(page.getByText(/required|enter a name/i).first()).toBeVisible();

  // Fill in valid data
  await page.getByPlaceholder(/Digital Signal Processing/i).fill('Signals & Systems');
  await page.getByPlaceholder(/EC301/i).fill('EE302');

  // Submit — should call POST /api/notebooks and close modal
  await page.getByRole('button', { name: /Create Notebook/i }).click();

  // Modal should close (heading disappears)
  await expect(page.getByRole('heading', { name: /New Notebook/i })).not.toBeVisible({ timeout: 5_000 });
});

// ─── Test 3: Navigate to an existing notebook ─────────────────────────────────

test('clicking a notebook card opens the notebook workspace', async ({ page }) => {
  await mockBaseAPI(page);

  // Mock the individual notebook endpoint
  await page.route(`${API}/api/notebooks/nb-001`, (route) =>
    route.fulfill({
      status: 200,
      contentType: 'application/json',
      body: JSON.stringify({
        id: 'nb-001',
        name: 'Digital Signal Processing',
        course: 'EC301 — DSP',
        created_at: new Date().toISOString(),
        sections: [],
        mastery_score: 0,
      }),
    })
  );

  await page.goto('/');
  await page.getByRole('button', { name: /Try Demo/i }).click();
  await page.waitForURL('**/dashboard', { timeout: 10_000 });

  // The notebook card should appear (name from mock list)
  const card = page.getByText('Digital Signal Processing').first();
  await expect(card).toBeVisible();
  await card.click();

  // Should navigate to /notebook/nb-001
  await page.waitForURL('**/notebook/nb-001', { timeout: 10_000 });
  await expect(page).toHaveURL(/notebook\/nb-001/);
});

// ─── Test 4: Register → login round-trip ──────────────────────────────────────

test('user can register and then log in', async ({ page }) => {
  await mockBaseAPI(page);

  await page.goto('/');

  // Switch to register tab / link if present
  const registerLink = page.getByRole('button', { name: /Sign up|Register|Create account/i });
  if (await registerLink.isVisible()) {
    await registerLink.click();
  }

  // Fill registration form
  const emailInput = page.getByPlaceholder(/email/i).first();
  const passwordInput = page.getByPlaceholder(/password/i).first();
  await emailInput.fill('newuser@test.com');
  await passwordInput.fill('password123');

  // Check for name field
  const nameInput = page.getByPlaceholder(/name|full name/i).first();
  if (await nameInput.isVisible()) {
    await nameInput.fill('New User');
  }

  const submitBtn = page.getByRole('button', { name: /sign up|register|create account/i }).first();
  if (await submitBtn.isVisible()) {
    await submitBtn.click();
    // Should reach dashboard or login after register
    await page.waitForURL(/dashboard|login/, { timeout: 10_000 });
  }

  // Navigate back to login if needed and log in
  if (page.url().includes('login')) {
    await page.getByPlaceholder(/email/i).first().fill('newuser@test.com');
    await page.getByPlaceholder(/password/i).first().fill('password123');
    await page.getByRole('button', { name: /sign in|log in/i }).first().click();
    await page.waitForURL('**/dashboard', { timeout: 10_000 });
  }

  await expect(page).toHaveURL(/dashboard/);
});
