# AIA interface and conversation search

The UI portion of this update renames the visible application to AIA and improves the chat layout,
including shorter Citrix windows, mobile screens, readable messages, tables,
response actions, and a composer that stays visible. The profile formats names
such as `Surname, Firstname [External]` as `Firstname Surname` with the first initial.

Conversation search now normalizes whitespace, case, accents and punctuation,
matches all search words in any order across titles and messages, and ranks title
matches before message matches. Results show highlighted excerpts and open the
matching message. The history view has explicit All, Active and Archived filters;
the global search includes archived conversations. Both searches have independent
state. Arrow keys and Enter navigate the search dialog.

Authentication and Lakebase ownership checks are unchanged. For the combined backend
upgrade included in the latest source, also follow [UPGRADE_DEEP_AGENT.md](UPGRADE_DEEP_AGENT.md).
The `atlas_*` database tables, storage keys, API headers and internal configuration
names remain compatible with existing chats. No database migration is required.

## Deploy

1. Upload the updated source folder to your workspace.
2. Preserve your Genie ID, index and Lakebase endpoint. Update the model settings
   and scopes using UPGRADE_DEEP_AGENT.md for the new combined workflow.
3. Select the folder directly containing `app.yaml` as the existing app's deployment
   source. The app service principal needs read access to this folder.
4. Deploy and refresh the app. Databricks builds the React assets during deployment.

## Verification

- 15 frontend tests passed, including eight search regression tests.
- TypeScript and Vite production build passed.
- Browser checks with synthetic, local-only conversations covered search matches,
  archived filters, independent search state, keyboard navigation, jumping to a
  matched message, profile formatting, and desktop/mobile layout.
- No live Azure backend calls were made for this UI verification.

The latest release integrates the new backend workflow; see UPGRADE_DEEP_AGENT.md
for its configuration and validation steps.
