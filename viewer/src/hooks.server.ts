import { SvelteKitAuth } from "@auth/sveltekit";
import GitHub from "@auth/sveltekit/providers/github";
import { env } from "$env/dynamic/private";
import jwt from "jsonwebtoken";
import { redirect, type Handle, type HandleFetch } from "@sveltejs/kit";
import { sequence } from "@sveltejs/kit/hooks";

const { AUTH_SECRET, GITHUB_ID, GITHUB_SECRET, ALLOWED_USERS } = env;

// 1. Configure Authentication (Auth.js)
const { handle: authHandle } = SvelteKitAuth({
  providers: [
    GitHub({
      clientId: GITHUB_ID,
      clientSecret: GITHUB_SECRET,
    }),
  ],
  secret: AUTH_SECRET,
  trustHost: true,
  callbacks: {
    async signIn({ user }) {
      // Enforce Email Allowlist
      const allowed = ALLOWED_USERS
        ? ALLOWED_USERS.split(",").map((u) => u.trim())
        : [];

      if (allowed.length === 0) {
        console.warn("Login attempt rejected: ALLOWED_USERS is empty.");
        return false;
      }

      if (user.email && allowed.includes(user.email)) {
        return true;
      }

      console.warn(`Access denied for user: ${user.email}`);
      return false;
    },
  },
});

// 2. Configure Authorization & Token Injection
const authorizationHandle: Handle = async ({ event, resolve }) => {
  // Check session (populated by authHandle)
  const session = await event.locals.auth();

  // Protect all routes except auth routes
  if (!session?.user) {
    if (!event.url.pathname.startsWith("/auth")) {
      throw redirect(303, "/auth/signin");
    }
  } else {
    // User is authenticated.
    // Generate a JWT signed with the shared AUTH_SECRET to authenticate with the Backend API.
    if (session.user.email && AUTH_SECRET) {
      try {
        const token = jwt.sign(
          {
            sub: session.user.email,
            name: session.user.name,
            aud: "2brain-api",
            iss: "2brain-viewer",
          },
          AUTH_SECRET,
          { expiresIn: "1h" },
        );
        event.locals.backendToken = token;
      } catch (e) {
        console.error("Failed to sign backend token", e);
      }
    }
  }

  return resolve(event);
};

// 3. Handle Fetch (Server-side requests to backend)
export const handleFetch: HandleFetch = async ({ request, fetch, event }) => {
  if (event.locals.backendToken) {
    request.headers.set("Authorization", `Bearer ${event.locals.backendToken}`);
  }
  return fetch(request);
};

// 4. Chain hooks
export const handle = sequence(authHandle, authorizationHandle);
