import { useEffect } from "react";
import { useRouter } from "expo-router";
import { useAuth } from "@/src/auth";

/**
 * Restricts a screen to Admin / Director only.
 *
 * Under ACCESS_SECURITY_V2 both `role` and (once backfilled) `roles: string[]`
 * exist on the /auth/me response. We check the union so this hook works before
 * and after every user's next-login backfill.
 *
 * On denial we redirect back to /home and return `denied=true`. Screens
 * should render a small "not authorised" placeholder while the redirect
 * is in flight to avoid a flash of protected UI.
 */
export function useAccessGuard(
  allowed: string[] = ["admin", "director"],
  allowedEmails?: string[],
) {
  const { user, loading } = useAuth();
  const router = useRouter();

  const roles = new Set<string>([
    ...(user?.role ? [user.role] : []),
    ...(((user as any)?.roles as string[] | undefined) || []),
  ]);
  const emailAllowed = !allowedEmails || allowedEmails.some(
    (email) => email.toLowerCase() === (user?.email || "").toLowerCase()
  );
  const permitted = !!user && emailAllowed && allowed.some((r) => roles.has(r));

  useEffect(() => {
    if (!loading && user && !permitted) {
      router.replace("/home");
    }
  }, [loading, user, permitted, router]);

  return { permitted, loading, user };
}
