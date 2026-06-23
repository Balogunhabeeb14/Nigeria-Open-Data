"use client";

import React, { useState, useRef } from "react";
import { ArrowRight, CheckCircle, Plus, Trash2, ShieldCheck, Database, LayoutTemplate, UploadCloud, FileSpreadsheet, X } from "lucide-react";

interface Props {
  onClose?: () => void;
}

export default function PublisherRegistrationForm({ onClose }: Props) {
  const [step, setStep] = useState(1);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [success, setSuccess] = useState(false);
  
  const fileInputRef = useRef<HTMLInputElement>(null);

  // Form State
  const [publisher, setPublisher] = useState({
    name: "",
    api_key: "", // Used internally as auth
    contact_email: "",
  });

  const [source, setSource] = useState({
    title: "", // Human readable title
    domain: "general",
  });
  
  const [datasetFile, setDatasetFile] = useState<File | null>(null);

  const [indicators, setIndicators] = useState([
    { id: "", name: "", unit: "" },
  ]);

  const handlePublisherChange = (e: React.ChangeEvent<HTMLInputElement>) => {
    setPublisher({ ...publisher, [e.target.name]: e.target.value });
  };

  const handleSourceChange = (e: React.ChangeEvent<HTMLInputElement | HTMLSelectElement>) => {
    setSource({ ...source, [e.target.name]: e.target.value });
  };

  const handleIndicatorChange = (index: number, e: React.ChangeEvent<HTMLInputElement | HTMLSelectElement>) => {
    const newIndicators = [...indicators];
    newIndicators[index] = { ...newIndicators[index], [e.target.name]: e.target.value };
    setIndicators(newIndicators);
  };

  const addIndicator = () => {
    setIndicators([...indicators, { id: "", name: "", unit: "" }]);
  };

  const removeIndicator = (index: number) => {
    setIndicators(indicators.filter((_, i) => i !== index));
  };
  
  const handleFileChange = (e: React.ChangeEvent<HTMLInputElement>) => {
    if (e.target.files && e.target.files[0]) {
      setDatasetFile(e.target.files[0]);
    }
  };

  const nextStep = () => {
    setError(null);
    if (step === 1) {
      if (!publisher.name || !publisher.api_key) {
        setError("Organization Name and Secure Access Token are required.");
        return;
      }
    } else if (step === 2) {
      if (!source.title) {
        setError("Please provide a title for your dataset.");
        return;
      }
      if (!datasetFile) {
        setError("Please upload your raw dataset file (CSV or Excel).");
        return;
      }
    }
    setStep(step + 1);
  };

  const prevStep = () => {
    setError(null);
    setStep(step - 1);
  };

  const submitForm = async () => {
    setError(null);
    if (indicators.some((i) => !i.id || !i.name)) {
      setError("Please fill out all required variable fields (Column Header, Display Name).");
      return;
    }

    setLoading(true);
    try {
      // 1. Create Publisher
      const pubRes = await fetch("/api/publishers", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(publisher),
      });

      if (!pubRes.ok) {
        const data = await pubRes.json();
        throw new Error(data.detail || "Failed to register organization.");
      }

      // Generate a technical source_id from the human readable title
      const source_id = source.title
        .toLowerCase()
        .replace(/[^a-z0-9]+/g, '_')
        .replace(/(^_|_$)/g, '');

      // 2. Register Source (Hidden Backend Engineering Details)
      const sourcePayload = {
        publisher_api_key: publisher.api_key,
        source_id: source_id,
        domain: source.domain,
        connector: "pipeline.connectors.generic.GenericFileConnector",
        transform: "pipeline.transforms.generic_transform.generic_transform",
        schedule: "0 * * * *",
        landing_dir: source_id,
        ingest_mode: "file",
        indicators: indicators,
      };

      const srcRes = await fetch("/api/sources", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(sourcePayload),
      });

      if (!srcRes.ok) {
        const data = await srcRes.json();
        throw new Error(data.detail || "Failed to configure dataset processing.");
      }
      
      // 3. Upload the Dataset File
      if (datasetFile) {
        const formData = new FormData();
        formData.append("file", datasetFile);
        formData.append("source_id", source_id);
        formData.append("publisher_api_key", publisher.api_key);
        
        const uploadRes = await fetch("/api/upload", {
          method: "POST",
          body: formData,
        });
        
        if (!uploadRes.ok) {
          const data = await uploadRes.json();
          throw new Error(data.detail || "Failed to upload the dataset file.");
        }
      }

      setSuccess(true);
    } catch (err: any) {
      setError(err.message);
    } finally {
      setLoading(false);
    }
  };

  if (success) {
    return (
      <div className="bg-white/90 backdrop-blur-2xl p-12 rounded-[2.5rem] shadow-2xl border border-green-100 text-center w-full max-w-2xl mx-auto transform transition-all duration-500">
        <div className="w-24 h-24 bg-green-50 rounded-full flex items-center justify-center mx-auto mb-6 shadow-inner">
          <CheckCircle className="w-12 h-12 text-green-500" />
        </div>
        <h2 className="text-4xl font-black text-slate-900 mb-4 tracking-tight">Data Published!</h2>
        <p className="text-lg text-slate-600 mb-10 leading-relaxed">
          Your dataset has been securely uploaded. It will be verified and automatically integrated into the national portal shortly.
        </p>
        <div className="flex gap-4 justify-center">
          <button
            onClick={() => window.location.reload()}
            className="bg-slate-900 hover:bg-slate-800 text-white font-bold py-3.5 px-8 rounded-2xl shadow-xl hover:shadow-2xl transition-all duration-300"
          >
            Upload Another Dataset
          </button>
          {onClose && (
            <button
              onClick={onClose}
              className="bg-slate-100 hover:bg-slate-200 text-slate-700 font-bold py-3.5 px-8 rounded-2xl transition-all duration-300"
            >
              Close Window
            </button>
          )}
        </div>
      </div>
    );
  }

  return (
    <div className="w-full max-w-4xl mx-auto bg-white/95 backdrop-blur-2xl rounded-[2.5rem] shadow-2xl border border-slate-100 overflow-hidden relative">
      <div className="absolute top-0 left-0 w-full h-1.5 bg-gradient-to-r from-emerald-400 via-primary-500 to-blue-500"></div>
      
      {onClose && (
        <button onClick={onClose} className="absolute top-6 right-6 text-slate-400 hover:text-slate-600 bg-slate-100 hover:bg-slate-200 p-2 rounded-full transition-colors">
          <X className="w-5 h-5" />
        </button>
      )}

      <div className="p-8 md:p-14">
        {/* Progress Bar */}
        <div className="flex items-center justify-between mb-12 relative px-4">
          <div className="absolute left-4 right-4 top-1/2 -translate-y-1/2 h-1.5 bg-slate-100 rounded-full -z-10"></div>
          <div 
            className="absolute left-4 top-1/2 -translate-y-1/2 h-1.5 bg-primary-500 rounded-full -z-10 transition-all duration-700 ease-out"
            style={{ width: `calc(${((step - 1) / 2) * 100}% - 2rem)` }}
          ></div>
          
          {[1, 2, 3].map((i) => (
            <div key={i} className={`w-12 h-12 rounded-2xl flex items-center justify-center font-bold shadow-md transition-all duration-500 ${step >= i ? 'bg-primary-600 text-white scale-110 shadow-primary-500/30' : 'bg-white text-slate-400 border-2 border-slate-100'}`}>
              {step > i ? <CheckCircle className="w-6 h-6" /> : i}
            </div>
          ))}
        </div>

        <h2 className="text-3xl md:text-4xl font-black text-slate-900 mb-3 flex items-center gap-4 tracking-tight">
          {step === 1 && <><ShieldCheck className="w-10 h-10 text-primary-500" /> Organization Profile</>}
          {step === 2 && <><UploadCloud className="w-10 h-10 text-blue-500" /> Data Upload</>}
          {step === 3 && <><LayoutTemplate className="w-10 h-10 text-emerald-500" /> Define Variables</>}
        </h2>
        <p className="text-slate-500 mb-10 text-lg">
          {step === 1 && "Confirm your organization details to authenticate this upload."}
          {step === 2 && "Provide your raw dataset file (Excel or CSV) for processing."}
          {step === 3 && "Help us understand what data columns you are sharing with the public."}
        </p>

        {error && (
          <div className="mb-8 p-5 bg-red-50 border border-red-100 rounded-2xl text-red-600 font-medium flex items-center gap-4 animate-in slide-in-from-top-4 duration-300">
            <div className="w-2.5 h-2.5 rounded-full bg-red-500 shrink-0"></div>
            {error}
          </div>
        )}

        <div className="space-y-6">
          {/* STEP 1: PUBLISHER */}
          {step === 1 && (
            <div className="space-y-7 animate-in fade-in slide-in-from-right-8 duration-500">
              <div>
                <label className="block text-sm font-bold text-slate-700 mb-2">Publishing Organization Name</label>
                <input
                  type="text"
                  name="name"
                  value={publisher.name}
                  onChange={handlePublisherChange}
                  placeholder="e.g. Federal Ministry of Health"
                  className="w-full bg-slate-50 border-2 border-slate-100 text-slate-900 rounded-2xl px-5 py-4 focus:bg-white focus:ring-4 focus:ring-primary-500/10 focus:border-primary-500 transition-all outline-none font-medium text-lg placeholder:text-slate-400"
                />
              </div>
              <div>
                <label className="block text-sm font-bold text-slate-700 mb-2">Publisher Access Token (Password)</label>
                <input
                  type="password"
                  name="api_key"
                  value={publisher.api_key}
                  onChange={handlePublisherChange}
                  placeholder="Enter your secure publisher token"
                  className="w-full bg-slate-50 border-2 border-slate-100 text-slate-900 rounded-2xl px-5 py-4 focus:bg-white focus:ring-4 focus:ring-primary-500/10 focus:border-primary-500 transition-all outline-none font-medium text-lg placeholder:text-slate-400"
                />
              </div>
              <div>
                <label className="block text-sm font-bold text-slate-700 mb-2">Official Contact Email <span className="text-slate-400 font-normal">(Optional)</span></label>
                <input
                  type="email"
                  name="contact_email"
                  value={publisher.contact_email}
                  onChange={handlePublisherChange}
                  placeholder="data-office@example.gov.ng"
                  className="w-full bg-slate-50 border-2 border-slate-100 text-slate-900 rounded-2xl px-5 py-4 focus:bg-white focus:ring-4 focus:ring-primary-500/10 focus:border-primary-500 transition-all outline-none font-medium text-lg placeholder:text-slate-400"
                />
              </div>
            </div>
          )}

          {/* STEP 2: UPLOAD DATASET */}
          {step === 2 && (
            <div className="space-y-8 animate-in fade-in slide-in-from-right-8 duration-500">
              <div className="grid grid-cols-1 md:grid-cols-2 gap-8">
                <div>
                  <label className="block text-sm font-bold text-slate-700 mb-2">Dataset Title</label>
                  <input
                    type="text"
                    name="title"
                    value={source.title}
                    onChange={handleSourceChange}
                    placeholder="e.g. National Health Facilities 2023"
                    className="w-full bg-slate-50 border-2 border-slate-100 text-slate-900 rounded-2xl px-5 py-4 focus:bg-white focus:ring-4 focus:ring-primary-500/10 focus:border-primary-500 transition-all outline-none font-medium text-lg placeholder:text-slate-400"
                  />
                </div>
                <div>
                  <label className="block text-sm font-bold text-slate-700 mb-2">Data Category</label>
                  <select
                    name="domain"
                    value={source.domain}
                    onChange={handleSourceChange}
                    className="w-full bg-slate-50 border-2 border-slate-100 text-slate-900 rounded-2xl px-5 py-4 focus:bg-white focus:ring-4 focus:ring-primary-500/10 focus:border-primary-500 transition-all outline-none font-medium text-lg appearance-none cursor-pointer"
                  >
                    <option value="general">General Purpose</option>
                    <option value="health">Health & Demographics</option>
                    <option value="economics">Economics & Finance</option>
                    <option value="agric">Agriculture</option>
                    <option value="education">Education</option>
                  </select>
                </div>
              </div>
              
              <div className="pt-2">
                <label className="block text-sm font-bold text-slate-700 mb-3">Upload Raw Data File</label>
                <div 
                  onClick={() => fileInputRef.current?.click()}
                  className={`w-full border-2 border-dashed rounded-[2rem] p-12 flex flex-col items-center justify-center cursor-pointer transition-all duration-300 ${datasetFile ? 'border-primary-500 bg-primary-50/50 scale-[1.01] shadow-lg shadow-primary-500/5' : 'border-slate-300 hover:border-primary-400 bg-slate-50 hover:bg-slate-100/50'}`}
                >
                  <input 
                    type="file" 
                    className="hidden" 
                    ref={fileInputRef}
                    accept=".csv, application/vnd.openxmlformats-officedocument.spreadsheetml.sheet, application/vnd.ms-excel"
                    onChange={handleFileChange}
                  />
                  {datasetFile ? (
                    <>
                      <div className="w-20 h-20 bg-white rounded-full shadow-sm flex items-center justify-center mb-5">
                        <FileSpreadsheet className="w-10 h-10 text-primary-500" />
                      </div>
                      <p className="text-xl font-bold text-slate-900">{datasetFile.name}</p>
                      <p className="text-base text-slate-500 mt-2 font-medium">{(datasetFile.size / 1024).toFixed(2)} KB • Click to choose a different file</p>
                    </>
                  ) : (
                    <>
                      <div className="w-20 h-20 bg-white rounded-full shadow-sm flex items-center justify-center mb-5">
                        <UploadCloud className="w-10 h-10 text-slate-400" />
                      </div>
                      <p className="text-xl font-bold text-slate-700">Click to browse your files</p>
                      <p className="text-base text-slate-500 mt-2 font-medium">Supports .CSV and .XLSX (max. 50MB)</p>
                    </>
                  )}
                </div>
              </div>
            </div>
          )}

          {/* STEP 3: INDICATORS / COLUMNS */}
          {step === 3 && (
            <div className="space-y-6 animate-in fade-in slide-in-from-right-8 duration-500">
              <div className="bg-blue-50 border border-blue-100 p-5 rounded-2xl text-sm text-blue-800 mb-6 flex items-start gap-3">
                <ShieldCheck className="w-5 h-5 text-blue-600 shrink-0 mt-0.5" />
                <p className="leading-relaxed font-medium">
                  Please identify the key variables in your dataset. The <strong>File Column Header</strong> must exactly match the column text in your uploaded spreadsheet.
                </p>
              </div>
              
              {indicators.map((indicator, index) => (
                <div key={index} className="p-7 bg-white shadow-sm border-2 border-slate-100 rounded-3xl relative group hover:border-primary-200 transition-colors">
                  <button 
                    onClick={() => removeIndicator(index)}
                    disabled={indicators.length === 1}
                    className="absolute top-5 right-5 text-slate-300 hover:text-red-500 disabled:opacity-0 transition-colors p-2 hover:bg-red-50 rounded-full"
                    title="Remove Variable"
                  >
                    <Trash2 className="w-5 h-5" />
                  </button>
                  
                  <div className="grid grid-cols-1 md:grid-cols-3 gap-5">
                    <div>
                      <label className="block text-[11px] font-bold text-slate-400 uppercase tracking-wider mb-2">File Column Header</label>
                      <input
                        type="text"
                        name="id"
                        value={indicator.id}
                        onChange={(e) => handleIndicatorChange(index, e)}
                        placeholder="e.g. patients_count"
                        className="w-full bg-slate-50 border border-slate-200 text-slate-900 rounded-xl px-4 py-3 text-sm focus:bg-white focus:ring-4 focus:ring-primary-500/10 focus:border-primary-500 outline-none font-medium transition-all"
                      />
                    </div>
                    <div>
                      <label className="block text-[11px] font-bold text-slate-400 uppercase tracking-wider mb-2">Public Display Name</label>
                      <input
                        type="text"
                        name="name"
                        value={indicator.name}
                        onChange={(e) => handleIndicatorChange(index, e)}
                        placeholder="e.g. Total Patients Admitted"
                        className="w-full bg-slate-50 border border-slate-200 text-slate-900 rounded-xl px-4 py-3 text-sm focus:bg-white focus:ring-4 focus:ring-primary-500/10 focus:border-primary-500 outline-none font-medium transition-all"
                      />
                    </div>
                    <div>
                      <label className="block text-[11px] font-bold text-slate-400 uppercase tracking-wider mb-2">Unit of Measurement</label>
                      <input
                        type="text"
                        name="unit"
                        value={indicator.unit}
                        onChange={(e) => handleIndicatorChange(index, e)}
                        placeholder="e.g. Persons, Naira, %"
                        className="w-full bg-slate-50 border border-slate-200 text-slate-900 rounded-xl px-4 py-3 text-sm focus:bg-white focus:ring-4 focus:ring-primary-500/10 focus:border-primary-500 outline-none font-medium transition-all"
                      />
                    </div>
                  </div>
                </div>
              ))}

              <button
                onClick={addIndicator}
                className="w-full py-5 border-2 border-dashed border-slate-200 bg-slate-50 hover:bg-primary-50 hover:border-primary-300 rounded-[2rem] flex items-center justify-center gap-2 text-slate-600 hover:text-primary-700 font-bold transition-all"
              >
                <Plus className="w-5 h-5" /> Add Another Variable
              </button>
            </div>
          )}
        </div>

        {/* Navigation Buttons */}
        <div className="mt-14 flex items-center justify-between pt-8 border-t border-slate-100">
          {step > 1 ? (
            <button
              onClick={prevStep}
              className="text-slate-500 hover:text-slate-900 font-bold px-6 py-3.5 rounded-2xl hover:bg-slate-100 transition-colors"
            >
              Go Back
            </button>
          ) : <div></div>}
          
          {step < 3 ? (
            <button
              onClick={nextStep}
              className="bg-slate-900 hover:bg-slate-800 text-white font-bold py-3.5 px-10 rounded-2xl shadow-xl hover:shadow-2xl hover:-translate-y-0.5 transition-all duration-300 flex items-center gap-3"
            >
              Continue <ArrowRight className="w-5 h-5" />
            </button>
          ) : (
            <button
              onClick={submitForm}
              disabled={loading}
              className="bg-primary-600 hover:bg-primary-700 disabled:opacity-70 disabled:cursor-not-allowed text-white font-bold py-3.5 px-10 rounded-2xl shadow-xl shadow-primary-500/20 hover:shadow-2xl hover:-translate-y-0.5 transition-all duration-300 flex items-center gap-3"
            >
              {loading ? "Publishing Data..." : "Publish Dataset to Portal"} <CheckCircle className="w-5 h-5" />
            </button>
          )}
        </div>
      </div>
    </div>
  );
}
