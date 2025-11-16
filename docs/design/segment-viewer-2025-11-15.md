# Improvements to segment viewer UI 15 November 2025

Please make the following changes to the chat/segment viewer page.
Always use standard Tailwind CSS and Daisy UI controls and styling when possible.
Always implement reactivity using Svelte 5 and Runes. You must not use the deprecated Svelte reactivity methods.

## Sidebar
- Make the sidebar collapsible
- Add a button to go back to the search page above the main content
### Sidebar cards
- Remove the pill showing the source, like (CHATGPT), and add a color-coded source bar on the left edge of the card. This should look like the bar used on segment cards on the right hand side.
- Before the segment count pill, add a total content character count pill (XXX charaters)
- Rather than "Updated MM DD, YYYY HH:MM" inline, show only DD MM YYYY, with the complete data as a delayed tooltip.

## Main Content
### Structure
- Combine the top two cards, wihch both logically concern the full segment and the user's view of it, into one card.
### Details
- Add a left bar to this merged first card that is a color-coded indication of the conversation's source. Remove the source attribution pill (CHATGPT)
- Before the Segment count pill, add a character count
- Move the "hide empty segments" button up and to the right of the Character count and Segment: count pills.
- Make the title of the conversation full with of the card  at the top.
- Move the date and time information, wihch is the the current right hand section of the first card, below the conversation title, still right justified. Show the date and time updated, labeled as "Updated: DD MM YYYY . Show the full date and time information for created, updated, and ingested as an expanded version of the Updated date in a tooltip.
- Below the row with Character Count, Segment count and Hide Empty Segments features, make a Full conversation row with:
    A left-justified label
    - a Full conversation label, same level as now
    Two right-justified buttons:
    - a View button, which does the current "Load transcript" function
    - a Dowload button, which does the current Download Markdow function.




- 

## Task List
1. **Expose per-document character counts end-to-end**
   - Update `DOCUMENT_LIST_SQL` and `list_documents` in `app/services/documents.py` plus the `DocumentSummary` schema to include `char_count`, summing `content_markdown` lengths for the latest version of each document.
   - Extend the viewer-side `DocumentSummary` type (`viewer/src/lib/types.ts`) and `+page.ts` loader to pass through `char_count`, including when hydrating a document fetched outside the initial list (compute from `initialDocument.segments` as a fallback).
   - Add a formatter/helper in `+page.svelte` that renders `NNN characters` so the sidebar and main card pills can reuse it.

2. **Make the documents sidebar collapsible and accessible**
   - Introduce a `$state` boolean (e.g., `sidebarOpen`) that controls whether the sidebar column is shown on small screens, defaulting to open on `md+`.
   - Add a toggle button with appropriate `aria-expanded`/`aria-controls` attributes in the sidebar header; collapse the sidebar content on mobile using conditional classes while keeping the desktop grid layout intact.
   - Ensure the main content expands to full width when the sidebar is collapsed and that the toggle remains reachable when the sidebar is hidden.

3. **Restyle sidebar document cards per the spec**
   - Remove the source pill badge and instead render a narrow, color-coded left bar that reflects `doc.source_system`, matching the style used for segment cards (create/reuse a helper to map a source to Tailwind classes).
   - Insert a character-count pill (`XXX characters`) before the segment-count pill; hide it if the count is missing.
   - Change the inline "Updated" text to show only `DD MM YYYY` and wrap it in a tooltip/title containing the full timestamp so hover/focus reveals the detailed value.
   - Preserve the current selection, hover, and disabled styles after the markup shuffle.

4. **Add a “Back to search” action above the main content**
   - Place a Daisy `btn` (with an arrow/chevron icon if available) at the top of `<main>` that links to `/search` so users can return to the search route without using the browser back button.
   - Ensure the button stays visible regardless of sidebar state and inherits spacing from the existing padding system.

5. **Merge and redesign the conversation summary + transcript cards**
   - Combine the two existing cards in `viewer/src/routes/+page.svelte` into a single card body and add a color-coded left accent bar driven by `selectedDocument.document.source_system`; remove the old source badge.
   - Let the conversation title span the card width, then move the date/time block below it on the right, rendering the label as `Updated: DD MM YYYY` with a tooltip that lists the precise Created/Updated/Ingested timestamps.
   - Immediately below that, render pills for character count (new) and segment count, and position the “Hide empty segments” toggle button on the same row flush-right; keep the hidden-count helper text nearby.
   - Follow with the existing summary/keyword sections as needed, then add a “Full conversation” row: label on the left, `View` button that calls `loadTranscript`, and `Download` button tied to `transcriptDownloadUrl`, preserving loading/disabled states.
   - Keep the transcript status/markdown output below this row within the same card, updating button text (“Load transcript” → “View”) and spacing to match the new structure.
