"use client";

import { useEffect, useRef } from "react";
import { markViewed } from "@/app/(app)/actions";

/** Registra la consultazione quando la scheda si apre davvero (non nei precaricamenti). */
export function MarkViewed({ propertyId }: { propertyId: string }) {
  const done = useRef(false);
  useEffect(() => {
    if (done.current) return;
    done.current = true;
    void markViewed(propertyId);
  }, [propertyId]);
  return null;
}
