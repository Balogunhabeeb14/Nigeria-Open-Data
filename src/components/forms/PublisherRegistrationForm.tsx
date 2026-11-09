import Link from "next/link";
export default function PublisherRegistrationForm({ onClose }: { onClose?: () => void }) {
  return <div className="bg-white rounded-xl p-8"><h2 className="text-2xl font-bold mb-4">Publish a dataset</h2><p className="mb-4">Create an account once and manage submissions through your publisher dashboard.</p><Link href="/publisher" className="text-blue-700 underline">Open publisher dashboard</Link>{onClose && <button onClick={onClose} className="block mt-4">Close</button>}</div>;
}
