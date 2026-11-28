package com.pipa.port95.logreporter;

import android.content.ContentProvider;
import android.content.ContentValues;
import android.content.Context;
import android.database.Cursor;
import android.database.MatrixCursor;
import android.net.Uri;
import android.os.ParcelFileDescriptor;
import android.provider.OpenableColumns;

import java.io.File;
import java.io.FileNotFoundException;
import java.util.regex.Pattern;

/**
 * Read-only provider for the report zips, so ACTION_SEND targets (Telegram, Files) get a content:// URI
 * with a one-off read grant instead of a file:// URI (FileUriExposedException).
 */
public final class ZipProvider extends ContentProvider {

    static final String AUTHORITY = "com.pipa.port95.logreporter.files";
    static final String MIME = "application/zip";
    private static final Pattern REPORT_NAME =
        Pattern.compile(Pattern.quote(LogCollector.ZIP_PREFIX) + "\\d{8}-\\d{6}\\.zip");

    /** Where reports live: app-specific external storage, or internal storage if it is unmounted. */
    static File dir(Context context) {
        File d = context.getExternalFilesDir(null);
        return d != null ? d : context.getFilesDir();
    }

    /** True for names the collector produces, e.g. pipa-oneui95-logs-20261128-153000.zip. */
    static boolean isReport(String name) {
        return name != null && REPORT_NAME.matcher(name).matches();
    }

    /** The newest report zip in {@code dir(context)}, or null if none has been collected yet. */
    static File latest(Context context) {
        File best = null;
        File[] files = dir(context).listFiles();
        for (File f : files != null ? files : new File[0]) {
            if (isReport(f.getName()) && f.isFile() && (best == null || f.lastModified() > best.lastModified())) {
                best = f;
            }
        }
        return best;
    }

    static Uri uriFor(File zip) {
        return new Uri.Builder().scheme("content").authority(AUTHORITY).appendPath(zip.getName()).build();
    }

    /** Trust boundary: a URI maps only to a bare report name inside dir(), never to a caller-built path. */
    private File resolve(Uri uri) throws FileNotFoundException {
        String name = uri.getPathSegments().size() == 1 ? uri.getLastPathSegment() : null;
        File f = isReport(name) ? new File(dir(getContext()), name) : null;
        if (f == null || !f.isFile()) {
            throw new FileNotFoundException(String.valueOf(uri));
        }
        return f;
    }

    @Override
    public boolean onCreate() {
        return true;
    }

    @Override
    public String getType(Uri uri) {
        return MIME;
    }

    @Override
    public ParcelFileDescriptor openFile(Uri uri, String mode) throws FileNotFoundException {
        if (!"r".equals(mode)) {
            throw new FileNotFoundException("read-only: " + mode);
        }
        return ParcelFileDescriptor.open(resolve(uri), ParcelFileDescriptor.MODE_READ_ONLY);
    }

    /** Answers OpenableColumns so receivers show the real file name and size. */
    @Override
    public Cursor query(Uri uri, String[] projection, String selection, String[] args, String sortOrder) {
        File f;
        try {
            f = resolve(uri);
        } catch (FileNotFoundException e) {
            return null;
        }
        String[] cols = projection != null ? projection
            : new String[] {OpenableColumns.DISPLAY_NAME, OpenableColumns.SIZE};
        Object[] row = new Object[cols.length];
        for (int i = 0; i < cols.length; i++) {
            if (OpenableColumns.DISPLAY_NAME.equals(cols[i])) {
                row[i] = f.getName();
            } else if (OpenableColumns.SIZE.equals(cols[i])) {
                row[i] = f.length();
            }
        }
        MatrixCursor cursor = new MatrixCursor(cols, 1);
        cursor.addRow(row);
        return cursor;
    }

    @Override
    public Uri insert(Uri uri, ContentValues values) {
        throw new UnsupportedOperationException("read-only");
    }

    @Override
    public int delete(Uri uri, String selection, String[] args) {
        throw new UnsupportedOperationException("read-only");
    }

    @Override
    public int update(Uri uri, ContentValues values, String selection, String[] args) {
        throw new UnsupportedOperationException("read-only");
    }
}
