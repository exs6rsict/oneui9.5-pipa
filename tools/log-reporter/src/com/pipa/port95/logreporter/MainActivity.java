package com.pipa.port95.logreporter;

import android.app.Activity;
import android.content.ClipData;
import android.content.Intent;
import android.graphics.Typeface;
import android.net.Uri;
import android.os.Bundle;
import android.view.View;
import android.widget.Button;
import android.widget.LinearLayout;
import android.widget.ScrollView;
import android.widget.TextView;

import java.io.File;
import java.io.FileInputStream;
import java.io.InputStream;
import java.io.OutputStream;

/** Tablet-sized screen: three large buttons over a scrolling status console. */
public final class MainActivity extends Activity implements View.OnClickListener, LogCollector.Listener {

    private static final int REQ_SAVE = 1;
    private static final String[] LABELS = {
        "Kumpulkan Semua Log (.zip)", "Bagikan ZIP (Share)", "Simpan Ke... (Downloads/USB)"};

    /** A unit of background work; any exception is reported in the console. */
    private interface Job {
        void run() throws Exception;
    }

    private final Button[] buttons = new Button[LABELS.length];
    private TextView console;
    private ScrollView scroll;

    @Override
    protected void onCreate(Bundle state) {
        super.onCreate(state);
        int pad = (int) (16 * getResources().getDisplayMetrics().density);
        LinearLayout root = new LinearLayout(this);
        root.setOrientation(LinearLayout.VERTICAL);
        root.setPadding(pad, pad, pad, pad);

        TextView title = new TextView(this);
        title.setText("OneUI95 Log Reporter - Xiaomi Pad 6 (pipa)");
        title.setTextSize(24);
        root.addView(title);

        for (int i = 0; i < LABELS.length; i++) {
            Button b = new Button(this);
            b.setText(LABELS[i]);
            b.setTextSize(20);
            b.setAllCaps(false);
            b.setMinHeight(4 * pad);
            b.setOnClickListener(this);
            root.addView(b, new LinearLayout.LayoutParams(LinearLayout.LayoutParams.MATCH_PARENT,
                LinearLayout.LayoutParams.WRAP_CONTENT));
            buttons[i] = b;
        }

        console = new TextView(this);
        console.setTypeface(Typeface.MONOSPACE);
        console.setTextIsSelectable(true);
        scroll = new ScrollView(this);
        scroll.addView(console);
        root.addView(scroll, new LinearLayout.LayoutParams(LinearLayout.LayoutParams.MATCH_PARENT, 0, 1f));
        setContentView(root);

        status("Folder ZIP: " + ZipProvider.dir(this));
        File last = ZipProvider.latest(this);
        status(last != null ? "ZIP terakhir: " + last.getName() : "Belum ada ZIP. Tekan \"" + LABELS[0] + "\".");
    }

    @Override
    public void onClick(View v) {
        if (v == buttons[0]) {
            runInBackground(new Job() {
                @Override
                public void run() throws Exception {
                    new LogCollector(ZipProvider.dir(MainActivity.this), MainActivity.this).collect();
                    status("Selesai. Tekan \"" + LABELS[1] + "\" atau \"" + LABELS[2] + "\".");
                }
            });
            return;
        }
        File zip = ZipProvider.latest(this);
        if (zip == null) {
            status("Belum ada ZIP. Tekan \"" + LABELS[0] + "\" dulu.");
        } else if (v == buttons[1]) {
            Uri uri = ZipProvider.uriFor(zip);
            Intent send = new Intent(Intent.ACTION_SEND).setType(ZipProvider.MIME)
                .putExtra(Intent.EXTRA_STREAM, uri).addFlags(Intent.FLAG_GRANT_READ_URI_PERMISSION);
            send.setClipData(ClipData.newRawUri(zip.getName(), uri));
            startActivity(Intent.createChooser(send, "Bagikan " + zip.getName()));
        } else {
            startActivityForResult(new Intent(Intent.ACTION_CREATE_DOCUMENT).addCategory(Intent.CATEGORY_OPENABLE)
                .setType(ZipProvider.MIME).putExtra(Intent.EXTRA_TITLE, zip.getName()), REQ_SAVE);
        }
    }

    @Override
    protected void onActivityResult(int request, int result, final Intent data) {
        final File zip = ZipProvider.latest(this);
        if (request != REQ_SAVE || result != RESULT_OK || data == null || data.getData() == null || zip == null) {
            return;
        }
        runInBackground(new Job() {
            @Override
            public void run() throws Exception {
                InputStream in = new FileInputStream(zip);
                try {
                    OutputStream out = getContentResolver().openOutputStream(data.getData());
                    try {
                        LogCollector.copy(in, out);
                    } finally {
                        out.close();
                    }
                } finally {
                    in.close();
                }
                status("Tersimpan: " + data.getData());
            }
        });
    }

    /** Appends one line to the console; safe from any thread. */
    @Override
    public void status(final String line) {
        runOnUiThread(new Runnable() {
            @Override
            public void run() {
                console.append(line + "\n");
                scroll.post(new Runnable() {
                    @Override
                    public void run() {
                        scroll.fullScroll(View.FOCUS_DOWN);
                    }
                });
            }
        });
    }

    /** Runs {@code job} off the UI thread with the buttons disabled until it ends. */
    private void runInBackground(final Job job) {
        setButtonsEnabled(false);
        new Thread(new Runnable() {
            @Override
            public void run() {
                try {
                    job.run();
                } catch (Exception e) {
                    status("GAGAL: " + e);
                } finally {
                    runOnUiThread(new Runnable() {
                        @Override
                        public void run() {
                            setButtonsEnabled(true);
                        }
                    });
                }
            }
        }, "log-reporter").start();
    }

    private void setButtonsEnabled(boolean enabled) {
        for (Button b : buttons) {
            b.setEnabled(enabled);
        }
    }
}
