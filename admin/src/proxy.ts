import { NextResponse, type NextRequest } from "next/server";
import { createServerClient } from "@supabase/ssr";
import { SUPABASE_PUBLISHABLE_KEY, SUPABASE_URL } from "@/lib/env";

const PUBLIC_PATHS = ["/login", "/setup"];

function redirect(request: NextRequest, pathname: string, response: NextResponse) {
  const url = request.nextUrl.clone();
  url.pathname = pathname;
  url.search = "";
  const redirectResponse = NextResponse.redirect(url);
  // Conserva i cookie di sessione eventualmente aggiornati.
  response.cookies.getAll().forEach((cookie) => redirectResponse.cookies.set(cookie));
  return redirectResponse;
}

export async function proxy(request: NextRequest) {
  const path = request.nextUrl.pathname;

  if (process.env.ADMIN_PREVIEW === "1" && process.env.VERCEL_ENV !== "production" && path.startsWith("/anteprima")) {
    return NextResponse.next();
  }

  let response = NextResponse.next({ request });
  if (!SUPABASE_URL || !SUPABASE_PUBLISHABLE_KEY) {
    return path === "/configurazione" ? response : redirect(request, "/configurazione", response);
  }

  const supabase = createServerClient(SUPABASE_URL, SUPABASE_PUBLISHABLE_KEY, {
    cookies: {
      getAll() {
        return request.cookies.getAll();
      },
      setAll(cookiesToSet) {
        cookiesToSet.forEach(({ name, value }) => request.cookies.set(name, value));
        response = NextResponse.next({ request });
        cookiesToSet.forEach(({ name, value, options }) => response.cookies.set(name, value, options));
      },
    },
  });

  // Verifica la sessione (e la rinnova se serve).
  const { data } = await supabase.auth.getClaims();
  const claims = data?.claims;
  const isPublic = PUBLIC_PATHS.includes(path);

  if (!claims) {
    return isPublic || path.startsWith("/api/") ? response : redirect(request, "/login", response);
  }

  const verified = claims.aal === "aal2";
  if (!verified) {
    return path === "/mfa" || path === "/esci" ? response : redirect(request, "/mfa", response);
  }

  const mustChangePassword = Boolean((claims.app_metadata as Record<string, unknown> | undefined)?.must_change_password);
  if (mustChangePassword && path !== "/password" && path !== "/esci") {
    return redirect(request, "/password", response);
  }

  if (path === "/login" || path === "/mfa" || path === "/setup") {
    return redirect(request, "/", response);
  }
  return response;
}

export const config = {
  matcher: ["/((?!_next/static|_next/image|favicon.ico|icon.png|brand/|robots.txt).*)"],
};
