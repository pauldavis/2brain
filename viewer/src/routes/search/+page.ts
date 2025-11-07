import type { PageLoad } from './$types';
import { env } from '$env/dynamic/public';

const RAW = env.PUBLIC_API_BASE || 'http://localhost:8000';
const API_BASE = RAW.endsWith('/') ? RAW : RAW + '/';

export const load = (async () => {
  return { apiBase: API_BASE };
}) satisfies PageLoad;
