import asyncio
from playwright.async_api import async_playwright
import db
import os

import session_log
from logging_config import get_logger

log = get_logger(__name__)

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
SESSION_FILE = os.path.join(BASE_DIR, 'session_auth.json')
TENANT_ID_FILE = os.path.join(BASE_DIR, 'tenant_id.txt')

# Globals for UI control
is_running = False
is_paused = False
worker_task = None

def load_auth():
    if os.path.exists(SESSION_FILE) and os.path.exists(TENANT_ID_FILE):
        with open(TENANT_ID_FILE, 'r') as f:
            tenant_id = f.read().strip()
        return SESSION_FILE, tenant_id
    return None, None

async def authenticate():
    """Opens a visible browser for the user to log in and saves cookies/tenantId."""
    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=False)
        context = await browser.new_context()
        page = await context.new_page()

        log.info("Please log in to Exxat in the opened browser window.")
        try:
            await page.goto("https://login.exxat.com/")
        except Exception as e:
            log.warning("Initial navigation note: %s", e)

        # Wait until the user navigates to the internship section
        log.info("Waiting for you to log in and click on the 'Internships' section...")
        await page.wait_for_url("**/internships**", timeout=0)  # wait indefinitely

        # Extract Tenant ID from URL (e.g. /site/65c084c37e3eb2725efe54c1/...)
        current_url = page.url
        try:
            tenant_id = current_url.split('/site/')[1].split('/')[0]
            with open(TENANT_ID_FILE, 'w') as f:
                f.write(tenant_id)
            log.info("Captured Tenant ID: %s", tenant_id)
        except Exception as e:
            log.error("Could not extract Tenant ID from %s. Error: %s", current_url, e)

        # Save session state (Cookies, LocalStorage)
        await context.storage_state(path=SESSION_FILE)
        log.info("Session saved successfully. You can close this window now if it doesn't close automatically.")
        await browser.close()

async def process_record(page, tenant_id, record):
    avail_id = record['availability_id']
    int_id = record['internship_id']
    disciplines = record['disciplines_to_set']

    url = f"https://one.exxat.com/site/{tenant_id}/internships/{int_id}?tab=details"

    def d(message, level="INFO"):
        """Detailed, per-record log line -> session live feed + detail file."""
        session_log.detail(message, level=level, avail_id=avail_id)

    # ---- small UI helpers (closures over `page` / `avail_id`) ---------------

    async def dismiss_association_popup():
        """Click OK on the 'Association Update' modal if it has popped up."""
        okay = page.locator('#new_associations_okay_btn')
        try:
            if await okay.count() > 0 and await okay.first.is_visible():
                d("Association Update popup detected -> clicking OK.")
                await okay.first.click(timeout=4000)
                await asyncio.sleep(0.1)
                return True
        except Exception as e:
            d(f"Failed handling Association Update popup: {e}", level="WARN")
        return False

    async def clear_dropdown_items():
        """Remove any currently-selected chips so we start from a clean set.

        Strategy:
        1. Try 'Clear All' button at the top level first.
        2. Find all accordion headers that have a checkmark (fa-check) SVG,
           expand each one, then click the 'Clear All' inside it.
        3. Fall back to clicking individual chip-close buttons with retry logic
           to handle cases where the list re-renders mid-clearing.
        """
        try:
            # ── Strategy 1: top-level "Clear All" ──────────────────────────
            clear_all = page.get_by_text("Clear All", exact=True)
            if await clear_all.count() > 0 and await clear_all.first.is_visible():
                d("Clicking top-level 'Clear All' to reset current selections.")
                await clear_all.first.click()
                await asyncio.sleep(0.1)
                remaining_chips = await page.locator('button[id^="chip-close-btn-"]').count()
                if remaining_chips == 0:
                    d("Top-level 'Clear All' succeeded.")
                    await asyncio.sleep(0.1)
                    return
                d(f"Top-level 'Clear All' left {remaining_chips} chip(s); continuing with accordion strategy.")

            # ── Strategy 2: expand each checked accordion and clear inside ──
            # Accordion headers that contain a fa-check SVG are disciplines
            # with at least one selected specialization.
            checked_headers = page.locator(
                'button.accordion-header:has(svg[data-icon="check"])'
            )
            header_count = await checked_headers.count()
            d(f"Found {header_count} accordion header(s) with checkmarks to expand and clear.")

            for i in range(header_count):
                try:
                    header = checked_headers.nth(i)
                    if not await header.is_visible():
                        continue

                    # Expand if not already open.
                    is_expanded = (await header.get_attribute("aria-expanded")) == "true"
                    if not is_expanded:
                        await header.click(timeout=3000)
                        await asyncio.sleep(0.1)
                        d(f"Expanded accordion #{i + 1}.")

                    # Look for 'Clear All' scoped inside the expanded panel.
                    parent = header.locator("xpath=../..")
                    clear_btn = parent.get_by_text("Clear All", exact=True)
                    if await clear_btn.count() > 0 and await clear_btn.first.is_visible():
                        d(f"Clicking 'Clear All' inside accordion #{i + 1}.")
                        await clear_btn.first.click(timeout=3000)
                        await asyncio.sleep(0.1)
                        await dismiss_association_popup()
                    else:
                        d(f"No 'Clear All' inside accordion #{i + 1}; will rely on chip fallback.")

                except Exception as e:
                    d(f"Accordion #{i + 1} clear attempt failed: {e}", level="WARN")
                    continue

            await asyncio.sleep(0.1)

            # ── Strategy 3: chip-by-chip fallback with retry loop ────────────
            MAX_ROUNDS = 10
            STALL_LIMIT = 3

            prev_count = -1
            stall_streak = 0

            for round_num in range(1, MAX_ROUNDS + 1):
                close_btns = page.locator('button[id^="chip-close-btn-"]')
                count = await close_btns.count()

                if count == 0:
                    d(f"All chips cleared after round {round_num - 1}.")
                    break

                if count == prev_count:
                    stall_streak += 1
                    d(f"Chip count unchanged at {count} (stall {stall_streak}/{STALL_LIMIT}).",
                      level="WARN")
                    if stall_streak >= STALL_LIMIT:
                        d(f"Chip removal stalled with {count} chip(s) remaining. Aborting.",
                          level="WARN")
                        break
                else:
                    stall_streak = 0

                d(f"Chip fallback round {round_num}: {count} chip(s) remaining.")
                prev_count = count

                all_ids = []
                for j in range(count):
                    try:
                        btn_id = await close_btns.nth(j).get_attribute("id")
                        if btn_id:
                            all_ids.append(btn_id)
                    except Exception:
                        pass

                for btn_id in all_ids:
                    try:
                        btn = page.locator(f'#{btn_id}')
                        if await btn.count() > 0 and await btn.first.is_visible():
                            await btn.first.click(timeout=1500)
                            await asyncio.sleep(0.1)
                    except Exception:
                        pass

                await asyncio.sleep(0.1)

        except Exception as e:
            d(f"clear_dropdown_items note: {e}", level="WARN")

        await asyncio.sleep(0.1)

    async def select_item(input_selector, item_name, kind, discipline_name=None):
        """Search `item_name` in an open dropdown and ensure it is selected.

        If `discipline_name` is provided, scopes the checkbox click to the
        accordion section for that discipline — prevents selecting the same
        spec name under the wrong discipline when duplicates exist across
        discipline accordions.
        """
        d(f"{kind}: searching for '{item_name}'"
          + (f" under discipline '{discipline_name}'" if discipline_name else "") + ".")
        inp = page.locator(input_selector)
        try:
            await inp.click(timeout=4000)
        except Exception as e:
            d(f"{kind}: could not focus search box for '{item_name}' ({e}).", level="WARN")
        try:
            await inp.fill("")
            await asyncio.sleep(0.1)
            await inp.fill(item_name)
        except Exception as e:
            d(f"{kind}: could not type '{item_name}' ({e}).", level="ERROR")
            return False
        await asyncio.sleep(0.1)  # let the list filter
        await dismiss_association_popup()

        # Strategy 1: checkbox-style rows (specializations / accordion lists).
        # If discipline_name is given, first try to scope to that accordion section.
        checkbox = page.locator('input[name="accordionCheckbox"]')
        cb_count = await checkbox.count()
        if cb_count > 0:
            d(f"{kind}: {cb_count} checkbox row(s) after filtering '{item_name}'.")

            if discipline_name:
                REVERSE_DISCIPLINE_MAPPING = {
                    'PT': 'Physical Therapy',
                    'PTA': 'Physical Therapist Assistant',
                    'OT': 'Occupational Therapy',
                    'OTA': 'Occupational Therapist Assistant',
                    'SLP': 'Speech-Language Pathology',
                }
                full_disc_name = REVERSE_DISCIPLINE_MAPPING.get(
                    discipline_name.upper(), discipline_name
                )

                # Find the accordion header whose label matches the discipline.
                disc_header = page.locator(
                    f'button.accordion-header:has(span.truncate:text-is("{full_disc_name}"))'
                )
                if await disc_header.count() == 0:
                    # Fallback: partial text match
                    disc_header = page.locator(
                        f'button.accordion-header:has(span:has-text("{full_disc_name}"))'
                    )

                if await disc_header.count() > 0:
                    # Expand if collapsed.
                    is_expanded = (await disc_header.first.get_attribute("aria-expanded")) == "true"
                    if not is_expanded:
                        await disc_header.first.click(timeout=3000)
                        await asyncio.sleep(0.1)
                        d(f"{kind}: expanded '{full_disc_name}' accordion to scope selection.")

                    # Scope checkboxes to the sibling content panel of this header.
                    accordion_wrapper = disc_header.locator("xpath=../..")
                    scoped_checkbox = accordion_wrapper.locator('input[name="accordionCheckbox"]')
                    scoped_count = await scoped_checkbox.count()
                    d(f"{kind}: {scoped_count} checkbox(es) scoped to '{full_disc_name}'.")

                    for i in range(scoped_count):
                        c = scoped_checkbox.nth(i)
                        try:
                            if not await c.is_visible():
                                continue
                            if await c.is_checked():
                                d(f"{kind}: '{item_name}' already selected under "
                                  f"'{full_disc_name}' (checkbox) - leaving as is.")
                                return True
                            await c.check(timeout=3000, force=True)
                            d(f"{kind}: SELECTED '{item_name}' under '{full_disc_name}' (scoped checkbox).")
                            await dismiss_association_popup()
                            return True
                        except Exception:
                            continue

                    d(f"{kind}: scoped search failed for '{item_name}' under "
                      f"'{full_disc_name}'; falling back to unscoped.", level="WARN")

            # Unscoped fallback — original behaviour.
            for i in range(cb_count):
                c = checkbox.nth(i)
                try:
                    if not await c.is_visible():
                        continue
                    if await c.is_checked():
                        d(f"{kind}: '{item_name}' already selected (checkbox) - leaving as is.")
                        return True
                    await c.check(timeout=3000, force=True)
                    d(f"{kind}: SELECTED '{item_name}' (checkbox unscoped).")
                    await dismiss_association_popup()
                    return True
                except Exception:
                    continue

        # Strategy 2: ARIA option items (typical for the Discipline combobox).
        option = page.get_by_role("option", name=item_name, exact=False)
        opt_count = await option.count()
        if opt_count > 0:
            d(f"{kind}: {opt_count} option(s) match '{item_name}'.")
            target = option.first
            try:
                if (await target.get_attribute("aria-selected")) == "true":
                    d(f"{kind}: '{item_name}' already selected (option) - leaving as is.")
                    return True
                await target.click(timeout=3000)
                d(f"{kind}: SELECTED '{item_name}' (option).")
                await dismiss_association_popup()
                return True
            except Exception as e:
                d(f"{kind}: failed clicking option '{item_name}' ({e}).", level="WARN")

        # Strategy 3: last resort - visible text match inside the listbox only.
        try:
            listbox = page.locator('[role="listbox"]')
            scope = listbox if await listbox.count() > 0 else page
            text_match = scope.get_by_text(item_name, exact=False)
            if await text_match.count() > 0:
                await text_match.first.click(timeout=3000)
                d(f"{kind}: SELECTED '{item_name}' (list text fallback).")
                await dismiss_association_popup()
                return True
        except Exception as e:
            d(f"{kind}: list-text fallback failed for '{item_name}' ({e}).", level="WARN")

        d(f"{kind}: '{item_name}' NOT FOUND in dropdown.", level="ERROR")
        return False

    async def click_when_enabled(locator, label, wait_ms=8000):
        """Wait for a button to be visible & enabled, then click it once."""
        try:
            await locator.first.wait_for(state="visible", timeout=wait_ms)
        except Exception:
            d(f"'{label}' button never became visible.", level="WARN")
            return False
        waited = 0
        while waited < wait_ms:
            try:
                if await locator.first.is_enabled():
                    break
            except Exception:
                pass
            await asyncio.sleep(0.1)
            waited += 500
        try:
            if not await locator.first.is_enabled():
                d(f"'{label}' button is still disabled (required fields may be missing).",
                  level="WARN")
                return False
            await locator.first.click(timeout=5000)
            d(f"Clicked '{label}'.")
            return True
        except Exception as e:
            d(f"Failed clicking '{label}': {e}", level="ERROR")
            return False

    # Mark the record as in-flight so it isn't picked up again.
    db.update_status(avail_id, 'PROCESSING', f"Started processing internship {int_id}.")
    d(f"=== Processing internship {int_id} (availability {avail_id}) ===")

    missing_items = []

    try:
        d("Loading internship page (up to 60s to settle)...")
        await page.goto(url, wait_until="networkidle", timeout=60000)

        # Hard sleep to ensure React completely finishes rendering.
        await asyncio.sleep(10)
        d(f"Page loaded. Current URL: {page.url}")

        # 1. Click the 'Edit basic information' pencil icon.
        d("Looking for 'Edit basic information' pencil icon...")
        btn_selector = 'button[aria-label="Edit basic information"]'
        try:
            await page.wait_for_selector(btn_selector, state="visible", timeout=30000)
        except Exception:
            pass  # fall back to the ID below

        btn = page.locator(btn_selector)
        if await btn.count() > 0:
            d("Found pencil icon by aria-label -> clicking.")
            await btn.first.click(timeout=10000)
        else:
            fallback_btn = page.locator('#view_and_track_availability_details_edit_basic_details_btn')
            if await fallback_btn.count() > 0:
                d("Found pencil icon by ID -> clicking.")
                await fallback_btn.first.click(timeout=10000)
            else:
                d("Pencil icon NOT FOUND on the page.", level="ERROR")
                raise Exception("Pencil icon not found on the page.")

        await page.wait_for_selector('text=Edit Availability', timeout=10000)
        d("'Edit Availability' drawer opened.")
        await asyncio.sleep(0.1)

        # Ensure we are on the '2. Basic Info' tab.
        try:
            await page.get_by_role("button", name="2. Basic Info").click(timeout=2000)
            d("Switched to '2. Basic Info' tab.")
            await asyncio.sleep(0.1)
        except Exception:
            d("Already on the Basic Info tab.")

        # # 2. Select Discipline(s).
        # REVERSE_DISCIPLINE_MAPPING = {
        #     'PT': 'Physical Therapy',
        #     'PTA': 'Physical Therapist Assistant',
        #     'OT': 'Occupational Therapy',
        #     'OTA': 'Occupational Therapist Assistant',
        #     'SLP': 'Speech-Language Pathology',
        # }
        # raw_acronyms = list(set([spec['disciplineName'] for spec in disciplines]))
        # unique_disciplines = [
        #     REVERSE_DISCIPLINE_MAPPING.get(a.upper(), a) for a in raw_acronyms
        # ]
        # d(f"Opening Discipline dropdown. Need {len(unique_disciplines)} "
        #   f"discipline(s): {', '.join(unique_disciplines)}")

        # await page.locator('button[aria-label="Discipline"]').click(timeout=5000)
        # await asyncio.sleep(0.1)
        # await dismiss_association_popup()
        # await clear_dropdown_items()

        # for disc in unique_disciplines:
        #     ok = await select_item('#availability_creation_discipline_selection', disc, "Discipline")
        #     if not ok:
        #         missing_items.append(f"Discipline: {disc}")

        # # Close the Discipline dropdown.
        # try:
        #     await page.locator('button[aria-label="Discipline"]').click(timeout=2000)
        #     d("Closed Discipline dropdown.")
        # except Exception:
        #     await page.keyboard.press("Escape")
        # await asyncio.sleep(0.1)
        # await dismiss_association_popup()

        # 2. Select Discipline(s). (SKIPPED - logging only)
        REVERSE_DISCIPLINE_MAPPING = {
            'PT': 'Physical Therapy',
            'PTA': 'Physical Therapist Assistant',
            'OT': 'Occupational Therapy',
            'OTA': 'Occupational Therapist Assistant',
            'SLP': 'Speech-Language Pathology',
        }

        raw_acronyms = list(set([spec['disciplineName'] for spec in disciplines]))
        unique_disciplines = [
            REVERSE_DISCIPLINE_MAPPING.get(a.upper(), a)
            for a in raw_acronyms
        ]

        d(
            f"Opening Discipline dropdown. Need {len(unique_disciplines)} "
            f"discipline(s): {', '.join(unique_disciplines)}"
        )
        d("Discipline selection is disabled. No UI actions performed.")
        for disc in unique_disciplines:
            d(f"Discipline: '{disc}' (SKIPPED)")

        # 3. Select Specialization(s).
        # No deduplication by name — instead we scope each selection to its
        # discipline accordion. PT/"OP Geriatrics" and PTA/"OP Geriatrics" are
        # separate checkboxes under separate accordion headers in the dropdown.
        spec_names = [s['specializationName'] for s in disciplines]
        d(f"Opening Specialization dropdown. Need {len(spec_names)} "
          f"specialization(s): {', '.join(spec_names)}")

        await page.locator('button[aria-label="Specialization"]').click(timeout=5000)
        await asyncio.sleep(0.1)
        await dismiss_association_popup()
        await clear_dropdown_items()

        for spec in disciplines:
            spec_name = spec['specializationName']
            disc_name = spec['disciplineName']
            ok = await select_item(
                '#availability_creation_specialization_selection',
                spec_name,
                "Specialization",
                discipline_name=disc_name  # scope to correct accordion
            )
            if not ok:
                missing_items.append(f"Specialization: {spec_name} (discipline={disc_name})")

        # Close the Specialization dropdown.
        try:
            await page.locator('button[aria-label="Specialization"]').click(timeout=2000)
            d("Closed Specialization dropdown.")
        except Exception:
            await page.keyboard.press("Escape")
        await asyncio.sleep(0.1)
        await dismiss_association_popup()

        # 4. Save once, then close via the X button.
        d("Clicking 'Save and Next' once (#stepper_next_btn)...")
        await dismiss_association_popup()
        next_btn = page.locator('#stepper_next_btn')
        saved = await click_when_enabled(next_btn, "Save and Next")
        await asyncio.sleep(2)
        await dismiss_association_popup()
        await asyncio.sleep(0.1)

        # Close the drawer with the X button.
        d("Closing the Edit Availability drawer via the X button...")
        close_btn = page.locator('#close_Edit_Availability')
        closed = False
        try:
            if await close_btn.count() > 0:
                await close_btn.first.click(timeout=5000)
                d("Clicked the X (close) button.")
                closed = True
            else:
                d("X (close) button not found; pressing Escape.", level="WARN")
                await page.keyboard.press("Escape")
        except Exception as e:
            d(f"Failed clicking the X button: {e}", level="WARN")
            await page.keyboard.press("Escape")
        await asyncio.sleep(2)
        await dismiss_association_popup()

        # 5. Decide outcome.
        if missing_items:
            msg = (f"Saved={saved}, Closed={closed}. Could not select "
                   f"{len(missing_items)} item(s): " + "; ".join(missing_items))
            db.update_status(avail_id, 'FAILED', msg)
            session_log.record_result(avail_id, int_id, 'FAILED', msg, spec_count=len(disciplines))
            d(f"Result: FAILED - {msg}", level="ERROR")
        elif not saved:
            msg = "Selections made but 'Save and Next' could not be clicked (button disabled?)."
            db.update_status(avail_id, 'FAILED', msg)
            session_log.record_result(avail_id, int_id, 'FAILED', msg, spec_count=len(disciplines))
            d(f"Result: FAILED - {msg}", level="ERROR")
        else:
            msg = (f"Selected {len(unique_disciplines)} discipline(s) and "
                   f"{len(disciplines)} specialization(s); saved and closed.")
            db.update_status(avail_id, 'SUCCESS', msg)
            session_log.record_result(avail_id, int_id, 'SUCCESS', msg, spec_count=len(disciplines))
            d(f"Result: SUCCESS - {msg}")

    except Exception as e:
        error_msg = str(e)
        db.update_status(avail_id, 'FAILED', f"UI Wizard Error: {error_msg}")
        session_log.record_result(avail_id, int_id, 'FAILED', f"UI Wizard Error: {error_msg}",
                                  spec_count=len(disciplines))
        d(f"Result: FAILED (exception) - {error_msg}", level="ERROR")
        log.exception("Failed %s: %s", avail_id, error_msg)

async def run_worker_loop():
    global is_running, is_paused

    session_file, tenant_id = load_auth()
    if not session_file:
        log.error("No session found. Please run authenticate() first.")
        is_running = False
        return

    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=False, slow_mo=500)
        context = await browser.new_context(storage_state=session_file)
        page = await context.new_page()

        is_running = True
        log.info("Worker started.")
        session_log.detail("Worker started; browser launched.")

        while is_running:
            if is_paused:
                await asyncio.sleep(0.1)
                continue

            record = db.get_next_pending()
            if not record:
                log.info("No pending records. Queue is empty.")
                session_log.detail("No pending records. Queue is empty.")
                break

            log.info("Processing Availability ID: %s", record['availability_id'])
            await process_record(page, tenant_id, record)

            # Human-like delay between records.
            await asyncio.sleep(2)

        await browser.close()
    is_running = False
    log.info("Worker stopped.")
    session_log.detail("Worker stopped.")

def start_worker():
    global worker_task, is_running, is_paused
    if not is_running:
        is_paused = False
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)
        loop.run_until_complete(run_worker_loop())

def pause_worker():
    global is_paused
    is_paused = True

def resume_worker():
    global is_paused
    is_paused = False

def stop_worker():
    global is_running
    is_running = False

if __name__ == "__main__":
    asyncio.run(authenticate())