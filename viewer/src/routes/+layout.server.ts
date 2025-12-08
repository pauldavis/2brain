import type { LayoutServerLoad } from './$types';

export const load = (async ({ locals }) => {
	// Pass the backend token to the client so it can be used for client-side fetches
	return {
		backendToken: locals.backendToken
	};
}) satisfies LayoutServerLoad;
