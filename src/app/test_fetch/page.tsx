"use client";
import React, { useEffect } from 'react';
export default function Test() {
  useEffect(() => {
    const d = Object.getOwnPropertyDescriptor(window, 'fetch');
    console.log("Fetch descriptor:", d);
  }, []);
  return <div>Test</div>;
}
