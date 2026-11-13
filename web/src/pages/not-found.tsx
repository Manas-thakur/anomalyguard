import { CompassIcon } from "lucide-react";
import { Link, useLocation } from "react-router";

import { EmptyState, useTitle } from "@/components/common";
import { Button } from "@/components/ui/button";

export function NotFoundPage() {
  const { pathname } = useLocation();
  useTitle("Not found");
  return (
    <div className="bg-card mt-8 rounded-xl border">
      <EmptyState icon={CompassIcon} title="Page not found" description={`Nothing lives at ${pathname}.`}>
        <Button asChild>
          <Link to="/">Go to Health</Link>
        </Button>
        <Button asChild variant="outline">
          <Link to="/runs">All runs</Link>
        </Button>
      </EmptyState>
    </div>
  );
}
