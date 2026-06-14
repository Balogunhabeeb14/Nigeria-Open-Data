import type { Metadata } from "next";
import { Eye, ShieldAlert, CheckCircle, Smartphone } from "lucide-react";

export const metadata: Metadata = {
  title: "Accessibility Statement",
  description: "Read about our WCAG 2.1 Level AA web compatibility efforts to make government datasets accessible to everyone.",
};

export default function AccessibilityPage() {
  return (
    <div className="container mx-auto px-4 py-12 max-w-3xl">
      <div className="mb-12 text-center md:text-left">
        <div className="bg-primary-50 w-16 h-16 rounded-2xl flex items-center justify-center mb-6 mx-auto md:mx-0">
          <Eye className="w-8 h-8 text-primary-600" />
        </div>
        <h1 className="text-4xl font-extrabold text-slate-900 mb-4 tracking-tight">Accessibility Statement</h1>
        <p className="text-lg text-slate-600 leading-relaxed">
          Nigeria Open Data is dedicated to ensuring that digital access to public resources remains accessible to all citizens, including individuals with disabilities.
        </p>
      </div>

      <div className="prose prose-slate max-w-none space-y-8 text-slate-600 leading-relaxed">
        
        <section className="space-y-3">
          <h2 className="text-2xl font-bold text-slate-900 flex items-center gap-2">
            <CheckCircle className="w-5 h-5 text-primary-600" /> WCAG Compliance Goals
          </h2>
          <p>
            We strive to conform our interface components with the **Web Content Accessibility Guidelines (WCAG) 2.1 Level AA** standards. Key optimization practices implemented on this site include:
          </p>
          <ul className="list-disc pl-6 space-y-2">
            <li><strong>Alt Text & Descriptions</strong>: Providing image alternates and descriptive links for screen-reader readability.</li>
            <li><strong>Keyboard Accessibility</strong>: Ensuring all dynamic search inputs, filtering checkboxes, and dataset buttons can be navigated completely via keyboard controls.</li>
            <li><strong>Color Contrast ratios</strong>: Structuring components with premium high-contrast HSL color schemes to support low-vision users.</li>
          </ul>
        </section>

        <section className="space-y-3">
          <h2 className="text-2xl font-bold text-slate-900 flex items-center gap-2">
            <Smartphone className="w-5 h-5 text-primary-600" /> Responsive Layouts
          </h2>
          <p>
            This portal is structured with fully responsive, mobile-first design guidelines to allow scaling across desktops, tablets, and mobile devices without losing core structural layouts.
          </p>
        </section>

        <section className="space-y-3">
          <h2 className="text-2xl font-bold text-slate-900 flex items-center gap-2">
            <ShieldAlert className="w-5 h-5 text-primary-600" /> Ongoing Enhancements
          </h2>
          <p>
            Digital accessibility is an ongoing effort. We perform continuous reviews and automated validation tests across the frontend to maintain compatibility with modern assistive technologies.
          </p>
        </section>

      </div>
    </div>
  );
}
