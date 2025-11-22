import type { PageLoad } from './$types';
const RAW = import.meta.env.PUBLIC_API_BASE ?? 'http://localhost:8100';
const API_BASE = RAW.endsWith('/') ? RAW : RAW + '/';

export const load = (async () => {
  return { apiBase: API_BASE };
}) satisfies PageLoad;
