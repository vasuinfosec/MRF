import React, { useState } from "react";
import { View, Text, StyleSheet, ScrollView, Platform, Linking, Image } from "react-native";
import { SafeAreaView } from "react-native-safe-area-context";
import { useRouter } from "expo-router";
import * as WebBrowser from "expo-web-browser";
import * as ExpoLinking from "expo-linking";

import { useAuth } from "@/src/auth";
import { theme } from "@/src/theme";
import { Btn, Card, H1, Muted, Label, Input, Body } from "@/src/components/ui";
import { api } from "@/src/api";

const DEMO = [
  { email: "siteeng@vasu.dev", role: "site_engineer", label: "Site Engineer" },
  { email: "pm@vasu.dev", role: "pm", label: "Project Manager" },
  { email: "gm@vasu.dev", role: "gm", label: "General Manager" },
  { email: "purchase@vasu.dev", role: "purchase", label: "Purchase Dept." },
  { email: "director@vasu.dev", role: "director", label: "Director" },
  { email: "admin@vasu.dev", role: "admin", label: "Admin (Masters)" },
];

export default function Login() {
  const { login, loginWithSessionId } = useAuth();
  const router = useRouter();
  const [busy, setBusy] = useState(false);
  const [customEmail, setCustomEmail] = useState("");
  const [err, setErr] = useState("");

  const seedAndLogin = async (email: string, role: string, label: string) => {
    setBusy(true); setErr("");
    try {
      try { await api("/seed", { method: "POST", token: null }); } catch (_e) { /* noop */ }
      await login(email, role, label);
      router.replace("/home");
    } catch (e: any) {
      setErr(e.message || "Login failed");
    }
    setBusy(false);
  };

  const googleLogin = async () => {
    setBusy(true); setErr("");
    try {
      const redirectUrl = Platform.OS === "web"
        ? (typeof window !== "undefined" ? window.location.origin + "/" : "/")
        : ExpoLinking.createURL("");
      const authUrl = `https://auth.emergentagent.com/?redirect=${encodeURIComponent(redirectUrl)}`;
      if (Platform.OS === "web") {
        window.location.href = authUrl;
      } else {
        const result = await WebBrowser.openAuthSessionAsync(authUrl, redirectUrl);
        if (result.type === "success" && result.url) {
          const m = result.url.match(/session_id=([^&]+)/);
          if (m) {
            await loginWithSessionId(m[1]);
            router.replace("/home");
          }
        }
      }
    } catch (e: any) { setErr(e.message || "Google login failed"); }
    setBusy(false);
  };

  const customLogin = async () => {
    if (!customEmail.trim()) return;
    await seedAndLogin(customEmail.trim(), "pm", "Project Manager");
  };

  return (
    <SafeAreaView style={styles.wrap} edges={["top", "bottom"]}>
      <ScrollView contentContainerStyle={styles.scroll}>
        <View style={styles.brand}>
          <View style={styles.logo}>
            <Text style={styles.logoText}>V</Text>
          </View>
          <Text style={styles.brandName}>VASU INFOSEC</Text>
          <Text style={styles.brandTag}>Material Requisition & Purchase Order System</Text>
        </View>

        <Card style={{ marginTop: 24 }} testID="login-card">
          <H1>Sign in</H1>
          <Muted style={{ marginTop: 4, marginBottom: 16 }}>
            Choose a demo role, use custom email, or sign in with Google.
          </Muted>

          <Btn
            testID="google-signin-btn"
            title={busy ? "Please wait…" : "Continue with Google"}
            variant="primary"
            onPress={googleLogin}
            disabled={busy}
          />

          <View style={styles.divider}>
            <View style={styles.line} />
            <Text style={styles.dividerText}>DEMO USERS</Text>
            <View style={styles.line} />
          </View>

          <View style={{ gap: 8 }}>
            {DEMO.map((d) => (
              <Btn
                key={d.email}
                testID={`demo-${d.role}-btn`}
                title={`Login as ${d.label}`}
                variant="outline"
                onPress={() => seedAndLogin(d.email, d.role, d.label)}
                disabled={busy}
              />
            ))}
          </View>

          <View style={{ marginTop: 20 }}>
            <Label>OR CUSTOM EMAIL (demo)</Label>
            <Input
              testID="custom-email-input"
              placeholder="your.name@company.com"
              autoCapitalize="none"
              keyboardType="email-address"
              value={customEmail}
              onChangeText={setCustomEmail}
            />
            <Btn testID="custom-login-btn" title="Sign in" variant="action" onPress={customLogin} disabled={busy || !customEmail} />
          </View>

          {err ? <Text style={styles.err} testID="login-error">{err}</Text> : null}
        </Card>

        <Card style={{ marginTop: 16, backgroundColor: theme.colors.surface }} testID="roles-info">
          <Label>ROLES IN THIS APP</Label>
          <Body style={{ marginTop: 6 }}>
            Approval chain: Site Engineer → PM → Purchase → GM → Director{"\n"}
            {"\n"}
            • Site Engineer — drafts & submits MRFs; records GRN{"\n"}
            • PM — authorises MRFs for their projects{"\n"}
            • Purchase — issues POs (auto-issued below GM threshold){"\n"}
            • GM — approves POs above GM threshold{"\n"}
            • Director — approves POs above Director threshold, full override{"\n"}
            • Admin — masters, users, thresholds (no approval authority)
          </Body>
        </Card>
      </ScrollView>
    </SafeAreaView>
  );
}

const styles = StyleSheet.create({
  wrap: { flex: 1, backgroundColor: theme.colors.surface },
  scroll: { padding: 16, paddingBottom: 40 },
  brand: { alignItems: "center", marginTop: 16 },
  logo: {
    width: 64, height: 64, borderRadius: 8, backgroundColor: theme.colors.primary,
    alignItems: "center", justifyContent: "center", marginBottom: 12,
  },
  logoText: { color: "#fff", fontSize: 32, fontWeight: "800" },
  brandName: { fontSize: 22, fontWeight: "800", letterSpacing: 2, color: theme.colors.text },
  brandTag: { fontSize: 12, color: theme.colors.textMuted, marginTop: 4, textAlign: "center" },
  divider: { flexDirection: "row", alignItems: "center", marginVertical: 20 },
  line: { flex: 1, height: 1, backgroundColor: theme.colors.border },
  dividerText: { fontSize: 10, fontWeight: "700", color: theme.colors.textMuted, letterSpacing: 1.5, marginHorizontal: 8 },
  err: { color: theme.colors.danger, marginTop: 12, fontSize: 13 },
});
