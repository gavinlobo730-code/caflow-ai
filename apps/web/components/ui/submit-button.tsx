import * as React from "react";
import { Loader2 } from "lucide-react";
import { Button, type ButtonProps } from "@/components/ui/button";

/**
 * A Button that shows an inline spinner and disables itself while `loading` is
 * true — so API-backed actions (Save / Send / Convert / Approve …) always give
 * feedback and can't be double-submitted.
 *
 * For the many hand-styled <button> elements in the app, the same effect is
 * achieved with `disabled={busy}` + the shared <Spinner/> from ui/skeleton;
 * use this component for new/shadcn-Button forms.
 */
export interface SubmitButtonProps extends ButtonProps {
  loading?: boolean;
  /** Text to show while loading; defaults to the normal children. */
  loadingText?: React.ReactNode;
}

export const SubmitButton = React.forwardRef<HTMLButtonElement, SubmitButtonProps>(
  ({ loading = false, loadingText, disabled, children, ...props }, ref) => {
    return (
      <Button ref={ref} disabled={disabled || loading} aria-busy={loading || undefined} {...props}>
        {loading && <Loader2 className="mr-2 h-4 w-4 animate-spin" aria-hidden="true" />}
        {loading ? loadingText ?? children : children}
      </Button>
    );
  },
);
SubmitButton.displayName = "SubmitButton";
