import './globals.css';
import type { Metadata } from 'next';
import { Inter } from 'next/font/google';

const inter = Inter({ subsets: ['latin'] });

export const metadata: Metadata = {
  title: 'SAWA Dashboard',
  description: 'Systematic Algorithmic Wealth Architecture',
};

export default function RootLayout({
  children,
}: {
  children: React.ReactNode;
}) {
  return (
    <html lang="en">
      <head>
        <script
          dangerouslySetInnerHTML={{
            __html: `
              if (typeof window !== 'undefined') {
                var d = Object.getOwnPropertyDescriptor(window, 'fetch');
                if (d && !d.set) {
                  Object.defineProperty(window, 'fetch', {
                    configurable: true,
                    enumerable: d.enumerable,
                    get: d.get,
                    set: function() {} 
                  });
                }
              }
            `,
          }}
        />
      </head>
      <body className={inter.className}>{children}</body>
    </html>
  );
}
