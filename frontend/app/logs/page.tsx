import { redirect } from "next/navigation";

// Logs moved into Settings → Logs. Keep the old route working for bookmarks.
export default function Page() {
  redirect("/settings");
}
