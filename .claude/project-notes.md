# Project notes

- The image needs `DATABASE_URL` (Postgres) and exits with a non-zero status without it, by design (AC-002.14).
- Smoke start of the image: `devbox run image-build && devbox run image-smoke` (starts a throwaway Postgres), not a
  bare `docker run`. This is also the `ci-extra` gate.
- Tests need Docker (testcontainers) or `TEST_DATABASE_URL`.
