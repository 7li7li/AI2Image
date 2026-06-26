# Repository Guidelines

## Project Structure & Module Organization

This repository combines a FastAPI backend with a Next.js frontend. Backend routes live in `api/`, business logic in `services/`, shared helpers in `utils/`, and scripts in `scripts/`. Tests are under `test/`. Frontend code is in `web/src/`, with routes in `web/src/app/`, UI in `web/src/components/`, stores in `web/src/store/`, and assets in `web/public/`. Docs and screenshots live in `docs/`, `assets/`, and `README.assets/`.

## Build, Test, and Development Commands

- `uv sync --frozen` installs Python dependencies from `uv.lock`.
- `uv run uvicorn main:app --reload --host 127.0.0.1 --port 8000` starts the API locally.
- `uv run python -m unittest discover -s test` runs the backend test suite.
- `cd web && npm ci` installs frontend dependencies from `package-lock.json`.
- `cd web && npm run dev` starts the Next.js dev server.
- `cd web && npm run build` creates the frontend export.
- `docker build -t yanai:local .` builds the combined app image.

## Coding Style & Naming Conventions

Python targets 3.13. Use 4-space indentation, type hints where practical, `snake_case` for functions and modules, and `PascalCase` for classes. Keep route definitions in `api/` and service behavior in `services/`.

TypeScript and React should follow existing Next.js patterns: route folders under `web/src/app/`, kebab-case component files, exported components in `PascalCase`, and hooks prefixed with `use`. ESLint is configured in `web/eslint.config.mjs`; Prettier plugins organize imports and Tailwind classes.

## Testing Guidelines

Backend tests use `unittest` and should be named `test_<feature>.py`. Keep tests deterministic; mock OpenAI, WebDAV, OAuth, storage, and channel behavior. Add focused tests for protocol parsing, quota/account leasing, storage backends, registration security, or API response shapes.

The frontend currently has no dedicated test script. For UI changes, at minimum run `npm run build` from `web/` and manually verify affected pages.

## Commit & Pull Request Guidelines

Recent commits use short imperative summaries, sometimes with conventional prefixes such as `feat:` and `fix:`. Follow that style: `fix image edit async result parsing` or `feat: support multimodal responses input`.

Pull requests should include a concise summary, validation steps, linked issues when relevant, and screenshots or recordings for UI changes. Note configuration or migration impacts, especially changes involving `config.example.json`, `.env.example`, Docker volumes, or storage backends.

## Security & Configuration Tips

Do not commit real `config.json`, `.env`, tokens, account credentials, generated runtime data, or database files. Use `config.example.json` and `.env.example` for documented defaults. Runtime state belongs in `data/`, mounted into Docker as shown in `docker-compose.yml`.
