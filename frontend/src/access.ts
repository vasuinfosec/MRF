export const ACCESS_ADMIN_EMAIL = (
  process.env.EXPO_PUBLIC_ACCESS_ADMIN_EMAIL ||
  "pundalik.shinde@vasuinfosec.com"
).trim().toLowerCase();

export function isAccessAdmin(user?: { email?: string | null } | null): boolean {
  return (user?.email || "").trim().toLowerCase() === ACCESS_ADMIN_EMAIL;
}
