import React, { useEffect } from "react";
import { View, ActivityIndicator } from "react-native";
import { useRouter } from "expo-router";
import { useAuth } from "@/src/auth";
import { theme } from "@/src/theme";

export default function Index() {
  const { user, loading } = useAuth();
  const router = useRouter();

  useEffect(() => {
    if (loading) return;
    if (user) router.replace("/home");
    else router.replace("/login");
  }, [user, loading, router]);

  return (
    <View style={{ flex: 1, justifyContent: "center", alignItems: "center", backgroundColor: theme.colors.bg }}>
      <ActivityIndicator color={theme.colors.primary} size="large" />
    </View>
  );
}
